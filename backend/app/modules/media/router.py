from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.integrations.object_storage import ObjectStorage, S3ObjectStorage, StorageUnavailable
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.media.schemas import DownloadUrlResponse, MediaAssetResponse, UploadCompletionRequest, UploadRequestCreate, UploadRequestResponse
from app.modules.media.service import MediaError, MediaService

router = APIRouter(prefix="/media", tags=["media"])
Session = Annotated[AsyncSession, Depends(get_session)]


def get_object_storage() -> ObjectStorage:
    return S3ObjectStorage()


def _service(session: Session, storage: Annotated[ObjectStorage, Depends(get_object_storage)]) -> MediaService:
    return MediaService(session, storage)


Service = Annotated[MediaService, Depends(_service)]


def _error(error: MediaError) -> HTTPException:
    return HTTPException(error.status_code, detail={"code": error.code, "message": error.message})


@router.post("/upload-requests", response_model=UploadRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_upload_request(body: UploadRequestCreate, claims: CurrentConsumer, service: Service) -> UploadRequestResponse:
    try:
        asset, upload_url, expires_at = await service.create_upload_request(claims.user_id, **body.model_dump())
    except MediaError as error:
        raise _error(error) from error
    return UploadRequestResponse(
        asset_id=asset.id,
        upload_url=upload_url,
        headers={"Content-Type": asset.mime_type, "x-amz-meta-sha256": asset.sha256},
        expires_at=expires_at,
    )


@router.post("/{asset_id}:complete", response_model=MediaAssetResponse)
async def complete_upload(asset_id: str, body: UploadCompletionRequest, claims: CurrentConsumer, service: Service) -> MediaAssetResponse:
    try:
        asset = await service.complete_upload(asset_id, claims.user_id, **body.model_dump())
    except MediaError as error:
        raise _error(error) from error
    return MediaAssetResponse(id=asset.id, status=asset.status, mime_type=asset.mime_type, size_bytes=asset.size_bytes)


@router.get("/{asset_id}/download-url", response_model=DownloadUrlResponse)
async def create_download_url(asset_id: str, claims: CurrentConsumer, service: Service) -> DownloadUrlResponse:
    try:
        url, expires_at = await service.download_url(asset_id, claims.user_id)
    except MediaError as error:
        raise _error(error) from error
    return DownloadUrlResponse(url=url, expires_at=expires_at)
