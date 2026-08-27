from __future__ import annotations

import argparse
import asyncio
import selectors
import sys
from collections.abc import Sequence

from app.core.database import SessionLocal
from app.core.settings import Settings
from app.modules.exports.service import enqueue_expired_export_cleanup
from app.modules.media.service import enqueue_expired_upload_cleanup


class ConfigurationError(Exception):
    pass


async def enqueue_cleanup_event() -> tuple[str, str]:
    try:
        settings = Settings()
    except ValueError as error:
        raise ConfigurationError from error
    if not settings.mysql_dsn:
        raise ConfigurationError

    async with SessionLocal() as session:
        try:
            event = enqueue_expired_upload_cleanup(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return event.event_id, event.event_type


async def enqueue_all_cleanup_events() -> tuple[tuple[str, str], tuple[str, str]]:
    try:
        settings = Settings()
    except ValueError as error:
        raise ConfigurationError from error
    if not settings.mysql_dsn:
        raise ConfigurationError

    async with SessionLocal() as session:
        try:
            media_event = enqueue_expired_upload_cleanup(session)
            export_event = enqueue_expired_export_cleanup(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return (
        (media_event.event_id, media_event.event_type),
        (export_event.event_id, export_event.event_type),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enqueue media maintenance events.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("enqueue-expired-upload-cleanup")
    subcommands.add_parser("enqueue-expired-cleanup")
    args = parser.parse_args(argv)

    if args.command not in {"enqueue-expired-upload-cleanup", "enqueue-expired-cleanup"}:
        parser.error("unknown command")

    try:
        enqueue = (
            enqueue_cleanup_event
            if args.command == "enqueue-expired-upload-cleanup"
            else enqueue_all_cleanup_events
        )
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) as runner:
                events = runner.run(enqueue())
        else:
            events = asyncio.run(enqueue())
    except ConfigurationError:
        print("Media cleanup enqueue configuration invalid. Check required application and MySQL configuration.", file=sys.stderr)
        return 2
    except Exception:
        print("Media cleanup enqueue failed. Check MySQL availability and configuration.", file=sys.stderr)
        return 2

    if args.command == "enqueue-expired-upload-cleanup":
        event_id, event_type = events
        print(f"event_id={event_id} event_type={event_type}")
    else:
        for event_id, event_type in events:
            print(f"event_id={event_id} event_type={event_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
