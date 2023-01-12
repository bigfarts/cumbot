import json
import re

import aiohttp
import tiktoken

STOP_SEQ = "###"


class ServerError(Exception):
   def __init__(self, payload):
       self.payload = payload

   def __str__(self):
       return self.payload["message"]


class Backend:

    MAX_INPUT_TOKENS = 2000

    def __init__(self, api_key):
        self.api_key = api_key
        self.tokenizer = tiktoken.get_encoding("gpt2")
        self.stop_seq = self.tokenizer.encode(STOP_SEQ)
        self.session = aiohttp.ClientSession()

    def pretty_format(self, prompt):
        return self.tokenizer.decode(prompt)

    async def request(self, prompt, **kwargs):
        async with self.session.post(
            "https://api.openai.com/v1/completions",
            json={
                "model": "text-davinci-003",
                "temperature": 1.0,
                "stream": True,
                "prompt": self.tokenizer.decode(prompt),
                "max_tokens": 4000 - self.MAX_INPUT_TOKENS,
                "stop": [self.tokenizer.decode(self.stop_seq)],
                **kwargs,
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.content:
                line = line.strip()
                if not line:
                    continue

                if not line.startswith(b"data: "):
                    raise ValueError(line)
                payload = line[6:]
                if payload == b"[DONE]":
                    break

                resp = json.loads(payload)
                if "error" in resp:
                    raise ServerError(resp["error"])
                yield resp

    def complete(self, prompt, **kwargs):
        return (
            part["choices"][0]["text"] async for part in self.request(prompt, **kwargs)
        )

    def make_preprompt(self, nickname, timestamp, channel_name, topic):
        return self.tokenizer.encode(
            f"""You are {nickname}.

You are in a Discord channel named #{channel_name}.{f" The topic of the channel is: {topic}" if topic else ""}
{STOP_SEQ}
"""
        )

    def make_line(self, entry, reference_entry=None):
        reference_entry = None

        if reference_entry is None:
            e = f"""{entry.nickname} – {entry.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}:
{entry.content.replace(STOP_SEQ, '')}
{STOP_SEQ}
"""
        else:
            e = f"""{entry.nickname} – {entry.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")} in reply to {reference_entry.nickname} - {reference_entry.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}:
{entry.content.replace(STOP_SEQ, '')}
{STOP_SEQ}
"""
        if not entry.content:
            e = e.rstrip()
        return self.tokenizer.encode(e)

    def make_postprompt(self, nickname, timestamp, reference_entry=None):
        return self.tokenizer.encode(
            f"""{nickname} – {timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}:
"""
        )

    def make_summary_preprompt(self, nickname, timestamp):
        return self.tokenizer.encode(
            f"""You are {nickname}. The current time is {timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")}. Summarize the following chat log.
{STOP_SEQ}
"""
        )

    def make_summary_postprompt(self):
        return self.tokenizer.encode("Summary:")
