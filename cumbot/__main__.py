import sys

import toml

from .backends import openai
from .bot import run_bot


def main():
    config = toml.load(sys.argv[1])

    run_bot(
        config["discord_token"],
        openai.Backend(config["openai_token"]),
        config.get("max_input_tokens"),
        config.get("extra_api_settings", {}),
    )


if __name__ == "__main__":
    main()
