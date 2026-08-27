from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.object_storage import ObjectStorage, StorageUnavailable
from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.modules.exports.models import ExportTask
from app.modules.exports.schemas import ExportTaskCreate
from app.modules.itineraries.models import Itinerary, ItineraryVersion
from app.modules.itineraries.service import ItineraryService
from app.modules.media.models import MediaAsset

EXPORT_REQUESTED_EVENT = "export_task.requested"
EXPORT_COMPLETED_EVENT = "export_task.completed"
EXPORT_EXPIRATION_CLEANUP_EVENT = "export_task.expiration_cleanup_requested"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOWNLOAD_URL_TTL_SECONDS = 300
EXPORT_OUTPUT_TTL = timedelta(days=7)


class ExportTaskError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code


class ExportTaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, requester_id: str, idempotency_key: str, body: ExportTaskCreate) -> ExportTask:
        itinerary = await self.session.get(Itinerary, body.itinerary_id)
        if itinerary is None or not await ItineraryService(self.session).can_export(itinerary, requester_id):
            raise ExportTaskError("ITINERARY_NOT_FOUND", "The itinerary is unavailable.", 404)
        existing = await self.session.scalar(select(ExportTask).where(
            ExportTask.requester_id == requester_id,
            ExportTask.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            requested_version_matches = (
                existing.itinerary_version_id == body.version_id
                if body.version_id
                else existing.version_no == body.version_no
            )
            if (existing.itinerary_id, existing.format) != (body.itinerary_id, body.format) or not requested_version_matches:
                raise ExportTaskError("IDEMPOTENCY_CONFLICT", "Idempotency-Key is already bound to another export request.")
            return existing
        statement = select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id)
        if body.version_id:
            statement = statement.where(ItineraryVersion.id == body.version_id)
        else:
            statement = statement.where(ItineraryVersion.version == body.version_no)
        version = await self.session.scalar(statement)
        if version is None:
            raise ExportTaskError("ITINERARY_VERSION_NOT_FOUND", "The itinerary version is unavailable.", 404)
        task = ExportTask(
            requester_id=requester_id,
            itinerary_id=itinerary.id,
            itinerary_version_id=version.id,
            version_no=version.version,
            format=body.format,
            idempotency_key=idempotency_key,
            snapshot_json=dict(version.snapshot),
        )
        self.session.add(task)
        await self.session.flush()
        self._enqueue(task)
        await self.session.commit()
        return task

    async def get(self, task_id: str, requester_id: str) -> ExportTask | None:
        task = await self.session.get(ExportTask, task_id)
        if task is None or task.requester_id != requester_id:
            return None
        itinerary = await self.session.get(Itinerary, task.itinerary_id)
        if itinerary is None or not await ItineraryService(self.session).can_export(itinerary, requester_id):
            return None
        return task

    async def retry(self, task_id: str, requester_id: str) -> ExportTask | None:
        task = await self.get(task_id, requester_id)
        if task is None:
            return None
        if task.status not in {"failed", "cancelled"}:
            raise ExportTaskError("EXPORT_RETRY_NOT_ALLOWED", "Only failed or cancelled exports can be retried.")
        task.status = "queued"
        task.progress = 0
        task.output_asset_id = None
        task.last_error_code = None
        task.last_error_message = None
        task.finished_at = None
        task.expires_at = None
        self._enqueue(task)
        await self.session.commit()
        return task

    async def start_attempt(self, task_id: str, trace_id: str | None = None) -> ExportTask | None:
        task = await self.session.scalar(select(ExportTask).where(ExportTask.id == task_id).with_for_update())
        if task is None or task.status != "queued":
            return None
        task.attempt_count += 1
        task.last_attempt_at = utc_now()
        task.trace_id = trace_id or task.trace_id or new_uuid()
        task.status = "running"
        task.progress = 10
        task.last_error_code = None
        task.last_error_message = None
        task.finished_at = None
        await self.session.flush()
        return task

    async def complete(self, task_id: str, document: bytes, storage: ObjectStorage) -> None:
        task = await self.session.get(ExportTask, task_id)
        if task is None or task.status != "running":
            return
        digest = sha256(document).hexdigest()
        object_key = f"exports/{task.requester_id}/{task.id}.docx"
        task.progress = 70
        etag = await storage.upload_bytes(
            key=object_key,
            data=document,
            mime_type=DOCX_MIME_TYPE,
            sha256=digest,
        )
        asset = MediaAsset(
            owner_id=task.requester_id,
            purpose="itinerary_export",
            mime_type=DOCX_MIME_TYPE,
            size_bytes=len(document),
            sha256=digest,
            object_key=object_key,
            status="completed",
            upload_expires_at=utc_now() + EXPORT_OUTPUT_TTL,
            etag=etag,
        )
        self.session.add(asset)
        await self.session.flush()
        task.output_asset_id = asset.id
        task.status = "succeeded"
        task.progress = 100
        task.finished_at = utc_now()
        task.expires_at = asset.upload_expires_at
        task.last_error_code = None
        task.last_error_message = None
        self._enqueue_completed(task)

    async def download_url(self, task_id: str, requester_id: str, storage: ObjectStorage) -> tuple[str, datetime]:
        task = await self.get(task_id, requester_id)
        if task is None:
            raise ExportTaskError("EXPORT_TASK_NOT_FOUND", "The export is unavailable.", 404)
        if task.status == "expired" or _has_expired(task.expires_at):
            raise ExportTaskError("EXPORT_EXPIRED", "The export has expired.")
        if task.status != "succeeded" or task.output_asset_id is None:
            raise ExportTaskError("EXPORT_NOT_READY", "The export is not ready for download.")
        asset = await self.session.get(MediaAsset, task.output_asset_id)
        if asset is None or asset.owner_id != requester_id or asset.status != "completed" or asset.mime_type != DOCX_MIME_TYPE:
            raise ExportTaskError("EXPORT_NOT_READY", "The export is not ready for download.")
        expires_at = datetime.now(UTC) + timedelta(seconds=DOWNLOAD_URL_TTL_SECONDS)
        try:
            return await storage.presign_attachment_get(
                key=asset.object_key,
                filename=f"itinerary-export-{task.id}.docx",
                expires_in=DOWNLOAD_URL_TTL_SECONDS,
            ), expires_at
        except StorageUnavailable as error:
            raise ExportTaskError("EXPORT_STORAGE_UNAVAILABLE", "Private export storage is unavailable.", 503) from error

    async def prepare_retry(self, task_id: str) -> None:
        task = await self.session.get(ExportTask, task_id)
        if task is None or task.status != "running":
            return
        task.status = "queued"
        task.progress = 0
        task.last_error_code = "EXPORT_STORAGE_UNAVAILABLE"
        task.last_error_message = "Private export storage is temporarily unavailable."
        await self.session.commit()

    async def finalize_failure(self, task_id: str) -> None:
        task = await self.session.get(ExportTask, task_id)
        if task is None or task.status != "queued":
            return
        task.status = "failed"
        task.progress = 100
        task.last_error_code = "EXPORT_STORAGE_UNAVAILABLE"
        task.last_error_message = "Private export storage is temporarily unavailable."
        task.finished_at = utc_now()
        self._enqueue_completed(task)

    def _enqueue(self, task: ExportTask) -> None:
        trace_id = new_uuid()
        task.trace_id = trace_id
        self.session.add(OutboxEvent(
            event_type=EXPORT_REQUESTED_EVENT,
            aggregate_type="export_task",
            aggregate_id=task.id,
            trace_id=trace_id,
            payload_json={
                "export_task_id": task.id,
                "itinerary_id": task.itinerary_id,
                "version_id": task.itinerary_version_id,
                "format": task.format,
            },
        ))

    def _enqueue_completed(self, task: ExportTask) -> None:
        self.session.add(OutboxEvent(
            event_type=EXPORT_COMPLETED_EVENT,
            aggregate_type="export_task",
            aggregate_id=task.id,
            trace_id=task.trace_id or new_uuid(),
            payload_json={
                "export_task_id": task.id,
                "status": task.status,
                "asset_id": task.output_asset_id,
                "error_code": task.last_error_code,
                "user_id": task.requester_id,
            },
        ))


def enqueue_expired_export_cleanup(session: AsyncSession, *, trace_id: str | None = None) -> OutboxEvent:
    """Add one periodic export expiration cleanup request to the current transaction."""
    event = OutboxEvent(
        event_type=EXPORT_EXPIRATION_CLEANUP_EVENT,
        aggregate_type="export_expiration_cleanup",
        aggregate_id=new_uuid(),
        trace_id=trace_id or new_uuid(),
        payload_json={},
    )
    session.add(event)
    return event


async def expire_succeeded_exports(
    session: AsyncSession,
    storage: ObjectStorage | None,
    *,
    now: datetime | None = None,
) -> int:
    """Durably expire completed export tasks and best-effort delete their objects."""
    now = now or utc_now()
    tasks = (
        await session.scalars(
            select(ExportTask)
            .where(
                ExportTask.status == "succeeded",
                ExportTask.expires_at.is_not(None),
                ExportTask.expires_at <= now,
            )
            .with_for_update()
        )
    ).all()
    asset_ids = [task.output_asset_id for task in tasks if task.output_asset_id is not None]
    assets = {}
    if asset_ids:
        assets = {
            asset.id: asset
            for asset in (await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(asset_ids)))).all()
        }
    for task in tasks:
        task.status = "expired"
    await session.flush()
    if storage is not None:
        for task in tasks:
            asset = assets.get(task.output_asset_id)
            if asset is None:
                continue
            try:
                await storage.delete_object(key=asset.object_key)
            except Exception:
                # The persisted task state prevents further access while storage recovers.
                pass
    return len(tasks)


def _has_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)
