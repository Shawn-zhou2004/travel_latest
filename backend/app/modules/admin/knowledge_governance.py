"""Pure policy for official knowledge-source freshness and version metadata."""

from datetime import datetime, timedelta
from typing import Literal


OfficialKnowledgeSourceType = Literal["poi", "rule", "template"]

_REVIEW_INTERVALS: dict[OfficialKnowledgeSourceType, timedelta | None] = {
    "poi": timedelta(days=90),
    "rule": timedelta(days=180),
    "template": None,
}


def derive_next_review_at(
    source_type: OfficialKnowledgeSourceType,
    reviewed_at: datetime,
) -> datetime | None:
    """Return the next required review time for an official source."""
    _require_utc(reviewed_at, field_name="reviewed_at")
    try:
        interval = _REVIEW_INTERVALS[source_type]
    except KeyError as error:
        raise ValueError(f"Unsupported official knowledge source type: {source_type!r}") from error
    return reviewed_at + interval if interval is not None else None


def validate_source_version(
    source_version: str,
    *,
    document_id: str | None = None,
    supersedes_document_id: str | None = None,
) -> None:
    """Validate a positive dotted-numeric version and non-self supersession."""
    if not isinstance(source_version, str) or not source_version:
        raise ValueError("source_version must be a non-empty textual version.")

    parts = source_version.split(".")
    if any(not part.isdecimal() for part in parts) or not any(int(part) > 0 for part in parts):
        raise ValueError("source_version must be a positive dotted-numeric textual version.")

    if document_id is not None and supersedes_document_id == document_id:
        raise ValueError("A source cannot supersede itself.")


def is_source_expired(next_review_at: datetime | None, now: datetime) -> bool:
    """Return whether a source's scheduled review is due at the supplied UTC time."""
    _require_utc(now, field_name="now")
    if next_review_at is None:
        return False
    _require_utc(next_review_at, field_name="next_review_at")
    return next_review_at <= now


def _require_utc(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be a UTC-aware datetime.")
