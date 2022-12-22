import argparse

from .backends import openai
from .bot import run_bot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--discord-token", required=True)
    parser.add_argument("--openai-token", required=True)
    args = parser.parse_args()

    run_bot(args.discord_token, openai.Backend(args.openai_token))


if __name__ == "__main__":
    main()
