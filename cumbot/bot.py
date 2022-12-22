import asyncio
import collections
import datetime
import re

import disnake
import disnake.ext.commands

from . import unichunker

LogEntry = collections.namedtuple(
    "LogEntry", ["id", "nickname", "timestamp", "content"]
)


MAX_LOG_ENTRIES = 200


def resolve_display_name(guild, id):
    member = guild.get_member(id)
    if member is None:
        return f"user{id}"
    return member.display_name


def resolve_channel_name(guild, id):
    channel = guild.get_channel(id)
    if channel is None:
        return f"#channel{id}"
    return f"#{channel.name}"


def cleanup_message(content, guild):
    return re.sub(
        "<#(\d+)>",
        lambda m: resolve_channel_name(guild, int(m.group(1))),
        re.sub(
            "<a?(:\w+:)\d+>",
            lambda m: m.group(1),
            re.sub(
                r"<@!?(\d+)>",
                lambda m: resolve_display_name(guild, int(m.group(1))),
                content,
            ),
        ),
    )


async def aflatten(gen):
    return [x async for x in gen]


FORGET_COMMAND_NAME = "forget"


def create_prompt(make_line, preprompt, entries, postprompt, max_input_tokens):
    body = []

    for entry in entries:
        if not entry.content:
            continue

        reference_log_entry = None
        if entry.reference is not None:
            reference = next(
                (e for e in entries if e.id == entry.reference.message_id),
                None,
            )
            if reference is not None:
                reference_log_entry = LogEntry(
                    reference.id,
                    resolve_display_name(reference.guild, reference.author.id),
                    reference.created_at,
                    cleanup_message(reference.content, reference.guild),
                )

        line_tokens = make_line(
            LogEntry(
                entry.id,
                resolve_display_name(entry.guild, entry.author.id),
                entry.created_at,
                cleanup_message(entry.content, entry.guild),
            ),
            reference_log_entry,
        )

        if (
            len(preprompt)
            + sum(len(chunk) for chunk in body)
            + len(line_tokens)
            + len(postprompt)
            > max_input_tokens
        ):
            break

        body.append(line_tokens)

    return [
        *preprompt,
        *(token for chunk in reversed(body) for token in chunk),
        *postprompt,
    ]


def run_bot(
    discord_api_key,
    backend,
    max_input_tokens=None,
    extra_api_settings=None,
    ignored_users=frozenset(),
):
    extra_api_settings = extra_api_settings or {}
    if max_input_tokens is None:
        max_input_tokens = backend.MAX_INPUT_TOKENS

    intents = disnake.Intents.default()
    intents.messages = True
    intents.message_content = True
    intents.members = True
    bot = disnake.ext.commands.InteractionBot(intents=intents)

    logs_lock = asyncio.Lock()
    logs = {}

    requests_locks_lock = asyncio.Lock()
    requests_locks = {}

    @bot.slash_command(name=FORGET_COMMAND_NAME, description="Add chat log break")
    async def forget(inter):
        await inter.send(
            embed=disnake.Embed(description="Please wait..."),
        )
        await inter.edit_original_response(
            embed=disnake.Embed(description="Okay, forgetting everything from here."),
            components=[
                disnake.ui.Button(
                    label="Unforget",
                    custom_id=f"unforget:{(await inter.original_message()).id}",
                )
            ],
        )
        async with logs_lock:
            try:
                del logs[inter.channel.id]
            except KeyError:
                pass

    @bot.event
    async def on_interaction(inter):
        if isinstance(
            inter, disnake.interactions.message.MessageInteraction
        ) and inter.data.custom_id.startswith("unforget:"):
            _, _, original_interaction_id = inter.data.custom_id.partition(":")
            await inter.channel.delete_messages(
                [disnake.Object(int(original_interaction_id))]
            )

    @bot.event
    async def on_raw_message_delete(message):
        async with logs_lock:
            try:
                del logs[message.channel_id]
            except KeyError:
                pass

    @bot.event
    async def on_message(message):
        if message.guild is None:
            return

        if message.author.id in ignored_users:
            return

        now = datetime.datetime.utcnow()
        nick = resolve_display_name(message.guild, bot.user.id)

        async with requests_locks_lock:
            if message.channel.id not in requests_locks:
                requests_locks[message.channel.id] = asyncio.Lock()
            request_lock = requests_locks[message.channel.id]

        async with logs_lock:
            if message.channel.id not in logs:
                log = collections.deque()
                logs[message.channel.id] = log

                async for entry in bot.get_channel(message.channel.id).history(
                    limit=MAX_LOG_ENTRIES, before=message
                ):
                    if (
                        entry.author.id == bot.user.id
                        and entry.interaction is not None
                        and entry.interaction.type
                        == disnake.InteractionType.application_command
                        and entry.interaction.name == FORGET_COMMAND_NAME
                        and entry.components
                    ):
                        break
                    log.appendleft(entry)
            log = logs[message.channel.id]

            if (
                message.author.id == bot.user.id
                and message.interaction is not None
                and message.interaction.type
                == disnake.InteractionType.application_command
                and message.interaction.name == FORGET_COMMAND_NAME
                and message.components
            ):
                return

            while len(log) > MAX_LOG_ENTRIES:
                log.popleft()
            log.append(message)
            entries = list(log)
            entries.reverse()

        if message.author == bot.user:
            return

        if bot.user not in message.mentions:
            return

        if request_lock.locked():
            await message.channel.send(
                embed=disnake.Embed(
                    color=disnake.Color.yellow(),
                    title="Hold up!",
                    description="I'm already replying, please wait for me to finish!",
                ),
                reference=message,
            )
            return

        async with request_lock:
            preprompt = backend.make_preprompt(
                nick,
                now,
                message.channel.name,
                (message.channel.topic or "").partition("---")[0].strip(),
            )

            reference_log_entry = None
            if message.reference is not None:
                reference = next(
                    (e for e in entries if e.id == message.reference.message_id),
                    None,
                )
                if reference is not None:
                    reference_log_entry = LogEntry(
                        reference.id,
                        resolve_display_name(reference.guild, reference.author.id),
                        reference.created_at,
                        cleanup_message(reference.content, reference.guild),
                    )

            postprompt = backend.make_postprompt(nick, now, reference_log_entry)

            inp = create_prompt(
                backend.make_line,
                preprompt,
                entries,
                postprompt,
                max_input_tokens,
            )
            print(backend.pretty_format(inp))
            print(len(inp))
            print("---")

            # summary_inp = create_prompt(
            #     backend,
            #     backend.make_summary_preprompt(nick, now),
            #     entries,
            #     backend.make_summary_postprompt(),
            # )
            # summary = "".join(
            #     await asyncio.wait_for(backend.complete(summary_inp), 30.0)
            # )
            # print(summary)
            # raise Exception

            async def do_response():
                async with message.channel.typing():
                    completion = await aflatten(
                        backend.complete(inp, **extra_api_settings)
                    )

                for chunk in unichunker.chunker("".join(completion), 2000):
                    await message.channel.send(chunk, reference=message)

            try:
                await asyncio.wait_for(do_response(), 30.0)
            except Exception as e:
                await message.channel.send(
                    embed=disnake.Embed(
                        color=disnake.Color.red(),
                        title="Error",
                        description=f"{e.__class__.__name__}: {e}",
                    )
                )
                raise

    bot.run(discord_api_key)
