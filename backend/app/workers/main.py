from __future__ import annotations

import argparse
import asyncio
import selectors
import sys
import logging
from collections.abc import Sequence
from contextlib import suppress
from urllib.parse import urlsplit

from app.core.database import SessionLocal
from app.core.settings import Settings
from app.events.consumer import RabbitMQEventConsumer, registered_routes
from app.events.publisher import RabbitMQEventBroker, publish_pending_events
from app.modules.ai_memory.projection_worker import open_memory_projection_worker
from app.workers.domain_handlers import register_domain_handlers
from app.workers.health import write_worker_heartbeat
from redis.asyncio import Redis


logger = logging.getLogger(__name__)


def validate_worker_configuration(settings: Settings) -> None:
    required = {
        "mysql_dsn": settings.mysql_dsn,
        "redis_url": settings.redis_url,
        "rabbitmq_url": settings.rabbitmq_url,
        "elasticsearch_url": settings.elasticsearch_url,
        "jwt_secret": settings.jwt_secret,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")
    if settings.jwt_secret and len(settings.jwt_secret) < 32:
        raise ValueError("jwt_secret must contain at least 32 characters")

    expected_schemes = {
        "mysql_dsn": ("mysql+pymysql", "mysql+aiomysql", "mysql"),
        "redis_url": ("redis", "rediss"),
        "rabbitmq_url": ("amqp", "amqps"),
        "elasticsearch_url": ("http", "https"),
    }
    for name, schemes in expected_schemes.items():
        value = str(required[name])
        if urlsplit(value).scheme not in schemes:
            raise ValueError(f"{name} must use one of: {', '.join(schemes)}")
        if "REPLACE_WITH" in value or "USERNAME" in value:
            raise ValueError(f"{name} still contains a placeholder")


async def run_worker(*, poll_interval: float = 1.0) -> None:
    settings = Settings()
    validate_worker_configuration(settings)
    register_domain_handlers()
    broker = RabbitMQEventBroker(settings.rabbitmq_url or "")
    await broker.connect()
    redis = Redis.from_url(settings.redis_url or "", socket_connect_timeout=2, socket_timeout=2)
    consumer_task: asyncio.Task[None] | None = None
    memory_projection_worker = None
    memory_projection_context = None
    routes = registered_routes.snapshot()
    if routes:
        consumer = RabbitMQEventConsumer(broker, SessionLocal, routes)
        consumer_task = asyncio.create_task(consumer.run())
    try:
        if settings.ai_enabled:
            try:
                memory_projection_context = open_memory_projection_worker(settings)
                memory_projection_worker = await memory_projection_context.__aenter__()
            except Exception:
                logger.exception("Private memory projection worker could not start.")
        try:
            while True:
                if consumer_task is not None and consumer_task.done():
                    consumer_task.result()
                async with SessionLocal() as session:
                    await publish_pending_events(session, broker)
                if memory_projection_worker is not None:
                    try:
                        await memory_projection_worker.drain()
                    except Exception:
                        logger.exception("Private memory projection drain failed.")
                try:
                    await write_worker_heartbeat(redis)
                except Exception:
                    logger.exception("Worker heartbeat could not be written.")
                await asyncio.sleep(poll_interval)
        finally:
            if memory_projection_worker is not None and memory_projection_context is not None:
                with suppress(Exception):
                    await memory_projection_context.__aexit__(None, None, None)
    finally:
        if consumer_task is not None:
            consumer_task.cancel()
            with suppress(asyncio.CancelledError):
                await consumer_task
        await redis.aclose()
        await broker.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Travel event worker")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate worker configuration and exit without connecting",
    )
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        validate_worker_configuration(settings)
    except ValueError as error:
        print(f"Worker configuration invalid: {error}", file=sys.stderr)
        return 2

    if args.check_config:
        print("Worker configuration is valid.")
        return 0

    try:
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())) as runner:
                runner.run(run_worker())
        else:
            asyncio.run(run_worker())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
