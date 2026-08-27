from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, TypeDecorator, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, new_uuid, utc_now


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


class ImmutableJSON(TypeDecorator[object]):
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> object:
        return _thaw_json(value)

    def process_result_value(self, value: object, dialect: object) -> object:
        return _freeze_json(value)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_pending", "published_at", "created_at", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload_json: Mapped[Mapping[str, object]] = mapped_column(ImmutableJSON(), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)


class ProcessedEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint("consumer_name", "event_id", name="uq_processed_events_consumer_event"),
    )

    consumer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("outbox_events.event_id"), nullable=False, index=True
    )
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)


_IMMUTABLE_ENVELOPE_FIELDS = (
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "trace_id",
    "payload_json",
)


def _prevent_immutable_field_mutation(target: object, value: object, oldvalue: object, initiator: object) -> object:
    if inspect(target).persistent and oldvalue != value:
        raise ValueError("Event identity and envelope fields are immutable after insert")
    return value


def _freeze_payload_assignment(target: OutboxEvent, value: object, oldvalue: object, initiator: object) -> object:
    return _freeze_json(value)


for _field in _IMMUTABLE_ENVELOPE_FIELDS:
    event.listen(getattr(OutboxEvent, _field), "set", _prevent_immutable_field_mutation, retval=True)

event.listen(OutboxEvent.payload_json, "set", _freeze_payload_assignment, retval=True)

for _field in ("id", "consumer_name", "event_id", "processed_at"):
    event.listen(getattr(ProcessedEvent, _field), "set", _prevent_immutable_field_mutation, retval=True)
