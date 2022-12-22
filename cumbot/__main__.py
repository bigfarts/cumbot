import sys

import toml

from .backends import openai
from .bot import run_bot


def main():
    config = toml.load(sys.argv[1])

    run_bot(
        config["discord_token"],
        openai.Backend(config["openai_token"]),
        frozenset(int(id) for id in config.get("ignored_users", [])),
    )


if __name__ == "__main__":
    main()
