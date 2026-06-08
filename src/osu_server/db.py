"""Local database administration CLI."""

from __future__ import annotations

import argparse
import asyncio
from typing import NoReturn, cast

from osu_server.config import load_config
from osu_server.infrastructure.database.admin import create_database_if_missing


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m osu_server.db")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _ = subparsers.add_parser("create", help="Create the configured database if missing")
    return parser


def _fail(message: str) -> NoReturn:
    raise SystemExit(message)


async def _create() -> None:
    config = load_config()
    if config.environment.lower() == "production":
        _fail("Refusing to create databases in production")

    created = await create_database_if_missing(str(config.database_url))
    if created:
        print("database created")
    else:
        print("database already exists")


def main() -> None:
    args = _build_parser().parse_args()
    command = cast("str", args.command)
    if command == "create":
        asyncio.run(_create())
        return
    _fail(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
