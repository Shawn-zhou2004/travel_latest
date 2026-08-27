from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.modules.admin.knowledge_governance import (
    derive_next_review_at,
    is_source_expired,
    validate_source_version,
)


REVIEWED_AT = datetime(2026, 8, 8, 12, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("source_type", "expected_days"),
    [("poi", 90), ("rule", 180)],
)
def test_derive_next_review_at_uses_official_source_type_policy(source_type: str, expected_days: int) -> None:
    assert derive_next_review_at(source_type, REVIEWED_AT) == REVIEWED_AT + timedelta(days=expected_days)  # type: ignore[arg-type]


def test_derive_next_review_at_does_not_schedule_templates() -> None:
    assert derive_next_review_at("template", REVIEWED_AT) is None


@pytest.mark.parametrize("source_type", ["", "community", "web"])
def test_derive_next_review_at_rejects_unsupported_source_type(source_type: str) -> None:
    with pytest.raises(ValueError, match="Unsupported official knowledge source type"):
        derive_next_review_at(source_type, REVIEWED_AT)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "reviewed_at",
    [
        datetime(2026, 8, 8, 12, 30),
        datetime(2026, 8, 8, 20, 30, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_derive_next_review_at_requires_datetime_utc(reviewed_at: datetime) -> None:
    with pytest.raises(ValueError, match="reviewed_at must"):
        derive_next_review_at("poi", reviewed_at)


@pytest.mark.parametrize("source_version", ["1", "1.0", "2.4.0", "0.1"])
def test_validate_source_version_accepts_positive_textual_versions(source_version: str) -> None:
    validate_source_version(source_version, document_id="source-new", supersedes_document_id="source-old")


@pytest.mark.parametrize(
    "source_version",
    ["", " ", "0", "0.0", "-1", "+1", "1.", ".1", "1..0", "v1", "1-beta", 1],
)
def test_validate_source_version_rejects_blank_nonpositive_or_nontextual_versions(source_version: object) -> None:
    with pytest.raises(ValueError, match="source_version"):
        validate_source_version(source_version)  # type: ignore[arg-type]


def test_validate_source_version_rejects_self_supersession() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        validate_source_version("2", document_id="source-1", supersedes_document_id="source-1")


@pytest.mark.parametrize(
    ("next_review_at", "now", "expected"),
    [
        (None, REVIEWED_AT, False),
        (REVIEWED_AT + timedelta(seconds=1), REVIEWED_AT, False),
        (REVIEWED_AT, REVIEWED_AT, True),
        (REVIEWED_AT - timedelta(seconds=1), REVIEWED_AT, True),
    ],
)
def test_is_source_expired_uses_an_inclusive_review_deadline(
    next_review_at: datetime | None,
    now: datetime,
    expected: bool,
) -> None:
    assert is_source_expired(next_review_at, now) is expected


@pytest.mark.parametrize(
    ("next_review_at", "now", "field_name"),
    [
        (REVIEWED_AT, datetime(2026, 8, 8, 12, 30), "now"),
        (REVIEWED_AT, datetime(2026, 8, 8, 20, 30, tzinfo=timezone(timedelta(hours=8))), "now"),
        (datetime(2026, 8, 8, 12, 30), REVIEWED_AT, "next_review_at"),
        (datetime(2026, 8, 8, 20, 30, tzinfo=timezone(timedelta(hours=8))), REVIEWED_AT, "next_review_at"),
    ],
)
def test_is_source_expired_requires_datetime_utc(
    next_review_at: datetime,
    now: datetime,
    field_name: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        is_source_expired(next_review_at, now)
