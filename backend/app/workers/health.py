from __future__ import annotations

from datetime import UTC, datetime

from redis.asyncio import Redis

WORKER_HEARTBEAT_KEY = "ai_travel:worker:heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 120
WORKER_HEARTBEAT_STALE_SECONDS = 30


async def write_worker_heartbeat(redis: Redis) -> None:
    await redis.set(
        WORKER_HEARTBEAT_KEY,
        datetime.now(UTC).isoformat(),
        ex=WORKER_HEARTBEAT_TTL_SECONDS,
    )


def worker_heartbeat_status(value: str | bytes | None, *, now: datetime | None = None) -> tuple[str, datetime | None]:
    if value is None:
        return "unavailable", None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    try:
        heartbeat_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "unavailable", None
    if heartbeat_at.tzinfo is None:
        return "unavailable", None
    current_time = now or datetime.now(UTC)
    age_seconds = (current_time - heartbeat_at.astimezone(UTC)).total_seconds()
    return ("healthy" if 0 <= age_seconds <= WORKER_HEARTBEAT_STALE_SECONDS else "stale"), heartbeat_at
