from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.object_storage import ObjectStorage, StorageUnavailable
from app.models.base import new_uuid
from app.models.outbox import OutboxEvent
from app.modules.chat.models import Conversation, ConversationMember
from app.modules.media.models import MediaAsset

UPLOAD_URL_TTL_SECONDS = 900
DOWNLOAD_URL_TTL_SECONDS = 300
MEDIA_UPLOAD_CLEANUP_EVENT = "media.expired_upload_cleanup_requested"


class MediaCleanupStorage(Protocol):
    def delete_object(self, *, key: str) -> Awaitable[None]: ...


class MediaError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


class MediaService:
    def __init__(self, session: AsyncSession, storage: ObjectStorage) -> None:
        self.session = session
        self.storage = storage

    async def create_upload_request(self, owner_id: str, *, purpose: str, mime_type: str, size_bytes: int, sha256: str) -> tuple[MediaAsset, str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(seconds=UPLOAD_URL_TTL_SECONDS)
        asset = MediaAsset(
            owner_id=owner_id,
            purpose=purpose,
            mime_type=mime_type,
            size_bytes=size_bytes,
            sha256=sha256.lower(),
            object_key=f"media/{owner_id}/{uuid4()}",
            upload_expires_at=expires_at,
        )
        try:
            url = await self.storage.presign_put(
                key=asset.object_key,
                mime_type=asset.mime_type,
                sha256=asset.sha256,
                expires_in=UPLOAD_URL_TTL_SECONDS,
            )
        except StorageUnavailable as error:
            raise MediaError(503, "MEDIA_STORAGE_UNAVAILABLE", "Private media storage is unavailable.") from error
        self.session.add(asset)
        await self.session.commit()
        await self.session.refresh(asset)
        return asset, url, expires_at

    async def complete_upload(self, asset_id: str, owner_id: str, *, etag: str, size_bytes: int) -> MediaAsset:
        asset = await self._owned_asset(asset_id, owner_id)
        if asset.status == "pending" and _upload_has_expired(asset.upload_expires_at):
            asset.status = "expired"
            await self._delete_expired_object(asset)
            await self.session.commit()
            raise MediaError(409, "MEDIA_ASSET_EXPIRED", "The media asset upload request has expired.")
        if asset.status == "expired":
            raise MediaError(409, "MEDIA_ASSET_EXPIRED", "The media asset upload request has expired.")
        if asset.status == "completed":
            if asset.etag == etag.strip('"') and asset.size_bytes == size_bytes:
                return asset
            raise MediaError(409, "MEDIA_ASSET_ALREADY_COMPLETED", "The media asset is already completed.")
        try:
            actual_size, actual_mime, actual_etag, actual_sha256 = await self.storage.head_object(key=asset.object_key)
        except StorageUnavailable as error:
            raise MediaError(409, "MEDIA_UPLOAD_NOT_FOUND", "The uploaded media object is unavailable.") from error
        if (
            actual_size != asset.size_bytes
            or size_bytes != asset.size_bytes
            or actual_mime.split(";", 1)[0].lower() != asset.mime_type
            or actual_etag != etag.strip('"')
            or actual_sha256 != asset.sha256
        ):
            raise MediaError(422, "MEDIA_UPLOAD_INVALID", "The uploaded media object does not match the upload request.")
        asset.etag = actual_etag
        asset.status = "completed"
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def download_url(self, asset_id: str, owner_id: str) -> tuple[str, datetime]:
        asset = await self.session.get(MediaAsset, asset_id)
        if asset is None or not await self._can_download(asset, owner_id):
            raise MediaError(404, "MEDIA_ASSET_NOT_FOUND", "The media asset is unavailable.")
        if asset.purpose == "itinerary_export":
            raise MediaError(404, "MEDIA_ASSET_NOT_FOUND", "The media asset is unavailable.")
        if asset.status == "expired":
            raise MediaError(409, "MEDIA_ASSET_EXPIRED", "The media asset upload request has expired.")
        if asset.status != "completed":
            raise MediaError(409, "MEDIA_ASSET_NOT_COMPLETED", "The media asset upload is not complete.")
        expires_at = datetime.now(UTC) + timedelta(seconds=DOWNLOAD_URL_TTL_SECONDS)
        try:
            return await self.storage.presign_get(key=asset.object_key, expires_in=DOWNLOAD_URL_TTL_SECONDS), expires_at
        except StorageUnavailable as error:
            raise MediaError(503, "MEDIA_STORAGE_UNAVAILABLE", "Private media storage is unavailable.") from error

    async def _can_download(self, asset: MediaAsset, user_id: str) -> bool:
        if asset.owner_id == user_id:
            return True
        member_id = await self.session.scalar(
            select(ConversationMember.id)
            .join(Conversation, Conversation.id == ConversationMember.conversation_id)
            .where(
                Conversation.avatar_asset_id == asset.id,
                ConversationMember.user_id == user_id,
                ConversationMember.left_at.is_(None),
            )
        )
        return member_id is not None

    async def _owned_asset(self, asset_id: str, owner_id: str) -> MediaAsset:
        asset = await self.session.get(MediaAsset, asset_id)
        if asset is None or asset.owner_id != owner_id:
            raise MediaError(404, "MEDIA_ASSET_NOT_FOUND", "The media asset is unavailable.")
        return asset

    async def _delete_expired_object(self, asset: MediaAsset) -> None:
        delete_object: Callable[..., Awaitable[None]] | None = getattr(self.storage, "delete_object", None)
        if delete_object is None:
            return
        try:
            await delete_object(key=asset.object_key)
        except Exception:
            # The asset remains expired even if its uploaded object cannot be removed now.
            pass


def enqueue_expired_upload_cleanup(session: AsyncSession, *, trace_id: str | None = None) -> OutboxEvent:
    """Add one periodic cleanup request to the caller's current transaction."""
    event = OutboxEvent(
        event_type=MEDIA_UPLOAD_CLEANUP_EVENT,
        aggregate_type="media_upload_cleanup",
        aggregate_id=new_uuid(),
        trace_id=trace_id or new_uuid(),
        payload_json={},
    )
    session.add(event)
    return event


async def expire_pending_uploads(
    session: AsyncSession,
    storage: MediaCleanupStorage | None,
    *,
    now: datetime | None = None,
) -> int:
    """Expire overdue uploads and make one best-effort deletion attempt each."""
    now = now or datetime.now(UTC)
    assets = (
        await session.scalars(
            select(MediaAsset).where(
                MediaAsset.status == "pending",
                MediaAsset.upload_expires_at.is_not(None),
                MediaAsset.upload_expires_at <= now,
            )
        )
    ).all()
    for asset in assets:
        asset.status = "expired"
    await session.flush()

    delete_object: Callable[..., Awaitable[None]] | None = getattr(storage, "delete_object", None)
    if delete_object is not None:
        for asset in assets:
            try:
                await delete_object(key=asset.object_key)
            except Exception:
                # Expiration is durable even if object storage is temporarily unavailable.
                pass
    return len(assets)


def _upload_has_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)
