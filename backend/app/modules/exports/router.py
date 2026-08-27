from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.integrations.object_storage import ObjectStorage, S3ObjectStorage, StorageUnavailable
from app.modules.auth.dependencies import CurrentAdmin, CurrentConsumer
from app.modules.exports.models import ExportTask
from app.modules.exports.schemas import ExportDownloadUrlResponse, ExportTaskCreate, ExportTaskResponse
from app.modules.exports.service import ExportTaskError, ExportTaskService

router = APIRouter(tags=["exports"])
Session = Annotated[AsyncSession, Depends(get_session)]
ExportTaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "expired"]


class AdminExportTaskResponse(BaseModel):
    id: str
    requester_id: str
    itinerary_id: str
    itinerary_version_id: str
    version_no: int
    format: Literal["docx"]
    status: ExportTaskStatus
    progress: int
    attempt_count: int
    last_attempt_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None


class AdminExportTaskPage(BaseModel):
    items: list[AdminExportTaskResponse]
    next_cursor: None = None


def get_object_storage() -> ObjectStorage:
    try:
        from app.core.settings import Settings

        settings = Settings()
        return S3ObjectStorage(settings, bucket=settings.s3_bucket_exports)
    except StorageUnavailable as error:
        raise HTTPException(
            503,
            detail={"code": "EXPORT_STORAGE_UNAVAILABLE", "message": "Private export storage is unavailable."},
        ) from error


def _response(task: object) -> ExportTaskResponse:
    return ExportTaskResponse.model_validate({
        "id": task.id,
        "itinerary_id": task.itinerary_id,
        "version_no": task.version_no,
        "format": task.format,
        "status": task.status,
        "progress": task.progress,
        "output_available": task.status == "succeeded" and task.output_asset_id is not None,
        "attempt_count": task.attempt_count,
        "last_error_code": task.last_error_code,
        "last_error_message": task.last_error_message,
        "finished_at": task.finished_at,
        "expires_at": task.expires_at,
    })


def _error(error: ExportTaskError) -> HTTPException:
    return HTTPException(error.status_code, detail={"code": error.code, "message": error.message})


@router.post("/export-tasks", response_model=ExportTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_export(
    body: ExportTaskCreate,
    claims: CurrentConsumer,
    session: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> ExportTaskResponse:
    try:
        return _response(await ExportTaskService(session).create(claims.user_id, idempotency_key, body))
    except ExportTaskError as error:
        raise _error(error) from error


@router.get("/export-tasks/{task_id}", response_model=ExportTaskResponse)
async def get_export(task_id: str, claims: CurrentConsumer, session: Session) -> ExportTaskResponse:
    task = await ExportTaskService(session).get(task_id, claims.user_id)
    if task is None:
        raise HTTPException(404, detail={"code": "EXPORT_TASK_NOT_FOUND", "message": "The export is unavailable."})
    return _response(task)


@router.post("/export-tasks/{task_id}/retry", response_model=ExportTaskResponse)
async def retry_export(task_id: str, claims: CurrentConsumer, session: Session) -> ExportTaskResponse:
    try:
        task = await ExportTaskService(session).retry(task_id, claims.user_id)
    except ExportTaskError as error:
        raise _error(error) from error
    if task is None:
        raise HTTPException(404, detail={"code": "EXPORT_TASK_NOT_FOUND", "message": "The export is unavailable."})
    return _response(task)


@router.get("/export-tasks/{task_id}/download-url", response_model=ExportDownloadUrlResponse)
async def export_download_url(
    task_id: str,
    claims: CurrentConsumer,
    session: Session,
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> ExportDownloadUrlResponse:
    try:
        url, expires_at = await ExportTaskService(session).download_url(task_id, claims.user_id, storage)
    except ExportTaskError as error:
        raise _error(error) from error
    return ExportDownloadUrlResponse(url=url, expires_at=expires_at)


def _require_platform_admin(claims: CurrentAdmin) -> None:
    if "platform_admin" not in claims.roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Platform admin role required."})


def _admin_response(task: ExportTask) -> AdminExportTaskResponse:
    return AdminExportTaskResponse(
        id=task.id,
        requester_id=task.requester_id,
        itinerary_id=task.itinerary_id,
        itinerary_version_id=task.itinerary_version_id,
        version_no=task.version_no,
        format=task.format,
        status=task.status,
        progress=task.progress,
        attempt_count=task.attempt_count,
        last_attempt_at=task.last_attempt_at,
        last_error_code=task.last_error_code,
        last_error_message=task.last_error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        finished_at=task.finished_at,
        expires_at=task.expires_at,
    )


@router.get("/admin/export-tasks", response_model=AdminExportTaskPage)
async def list_admin_export_tasks(
    claims: CurrentAdmin,
    session: Session,
    status: ExportTaskStatus | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> AdminExportTaskPage:
    _require_platform_admin(claims)
    statement = select(ExportTask).order_by(ExportTask.updated_at.desc()).limit(limit)
    if status:
        statement = statement.where(ExportTask.status == status)
    tasks = (await session.scalars(statement)).all()
    return AdminExportTaskPage(items=[_admin_response(task) for task in tasks])
