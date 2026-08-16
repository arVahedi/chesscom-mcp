"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence

from .config import Config
from .errors import AppError
from .server import create_server
from .transport import run_http


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Chess.com MCP server")
    parser.add_argument("--transport", choices=("stdio", "http"), default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        config = Config.from_env(os.environ, transport_override=args.transport)
    except AppError as exc:
        print(f"Configuration error: {exc.message}", file=sys.stderr)
        raise SystemExit(2) from None
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    server = create_server(config)
    if config.transport == "http":
        run_http(server, config)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
