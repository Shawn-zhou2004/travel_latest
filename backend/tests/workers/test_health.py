from datetime import UTC, datetime, timedelta

from app.workers.health import worker_heartbeat_status


def test_worker_heartbeat_status_distinguishes_fresh_stale_and_invalid_values() -> None:
    now = datetime(2026, 8, 9, 15, 0, tzinfo=UTC)
    fresh_status, fresh_at = worker_heartbeat_status((now - timedelta(seconds=30)).isoformat(), now=now)
    stale_status, stale_at = worker_heartbeat_status((now - timedelta(seconds=31)).isoformat(), now=now)
    invalid_status, invalid_at = worker_heartbeat_status("not-a-timestamp", now=now)

    assert fresh_status == "healthy" and fresh_at is not None
    assert stale_status == "stale" and stale_at is not None
    assert invalid_status == "unavailable" and invalid_at is None
