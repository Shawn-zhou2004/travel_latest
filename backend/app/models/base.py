import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.dialects import mysql
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_uuid() -> str:
    return str(uuid.uuid4())


def validate_uuid_v4(value: str, field_name: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a UUID v4") from error
    if parsed.version != 4:
        raise ValueError(f"{field_name} must be a UUID v4")
    return str(parsed)


def utc_now() -> datetime:
    return datetime.now(UTC)


UTCDateTime = mysql.DATETIME(fsp=6).with_variant(DateTime(timezone=True), "sqlite")


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


@event.listens_for(Base, "attribute_instrument", propagate=True)
def validate_public_identifier_assignment(cls: type[Any], key: str, inst: Any) -> None:
    if key not in {"id", "user_id", "event_id", "aggregate_id", "trace_id", "scope_key"}:
        return

    def validate(target: object, value: str | None, oldvalue: object, initiator: object) -> str | None:
        if value is None or (key == "scope_key" and value == ""):
            return value
        return validate_uuid_v4(value, key)

    event.listen(inst, "set", validate, retval=True)
