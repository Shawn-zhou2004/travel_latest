from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.settings import Settings
from app.models.user import UserSettings
from app.modules.ai_memory import AIMemoryRepository, AsyncpgPoolFactory
from app.modules.ai_workflows.schemas import GenerationJobCreate, GenerationJobResponse
from app.modules.ai_workflows.schemas import GenerationPreviewResponse
from app.modules.ai_workflows.service import GenerationJobError, GenerationJobService
from app.modules.auth.dependencies import CurrentAuthenticated, CurrentConsumer
from app.modules.itineraries.schemas import OperationResponse
from app.modules.itineraries.service import ItineraryService


router = APIRouter(prefix="/generation-jobs", tags=["ai-generation"])
Session = Annotated[AsyncSession, Depends(get_session)]


def settings_pace_to_generation_pace(value: str) -> Literal["slow", "balanced", "fast"]:
    return {"relaxed": "slow", "balanced": "balanced", "packed": "fast"}[value]


async def _effective_generation_request(
    session: AsyncSession, user_id: str, body: GenerationJobCreate
) -> GenerationJobCreate:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        await session.flush()
    updates: dict[str, object] = {}
    if "preference_tags" not in body.model_fields_set:
        updates["preference_tags"] = list(settings.interest_tags[:3])
    if "pace" not in body.model_fields_set:
        updates["pace"] = settings_pace_to_generation_pace(settings.travel_pace)
    if "traveler_type" not in body.model_fields_set:
        updates["traveler_type"] = settings.traveler_type
    return body.model_copy(update=updates)


def _is_admin(claims: CurrentAuthenticated) -> bool:
    return claims.audience == "admin" and "platform_admin" in claims.roles


@router.post("", response_model=GenerationJobResponse, status_code=status.HTTP_201_CREATED)
async def create_generation_job(
    body: GenerationJobCreate,
    claims: CurrentConsumer,
    session: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> GenerationJobResponse:
    try:
        body = await _effective_generation_request(session, claims.user_id, body)
        job = await GenerationJobService(session).create(claims.user_id, idempotency_key, body)
    except GenerationJobError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return GenerationJobResponse.model_validate(job)


@router.get("", response_model=list[GenerationJobResponse])
async def list_pending_generation_jobs(claims: CurrentAuthenticated, session: Session) -> list[GenerationJobResponse]:
    jobs = await GenerationJobService(session).list_pending(claims.user_id, is_admin=_is_admin(claims))
    return [GenerationJobResponse.model_validate(job) for job in jobs]


@router.get("/{job_id}", response_model=GenerationJobResponse)
async def get_generation_job(job_id: str, claims: CurrentAuthenticated, session: Session) -> GenerationJobResponse:
    job = await GenerationJobService(session).get(job_id, claims.user_id, is_admin=_is_admin(claims))
    if job is None:
        raise HTTPException(404, detail={"code": "GENERATION_JOB_NOT_FOUND", "message": "The generation job is unavailable."})
    return GenerationJobResponse.model_validate(job)


@router.post("/{job_id}/retry", response_model=GenerationJobResponse)
async def retry_generation_job(job_id: str, claims: CurrentAuthenticated, session: Session) -> GenerationJobResponse:
    try:
        job = await GenerationJobService(session).retry(job_id, claims.user_id, is_admin=_is_admin(claims))
    except GenerationJobError as error:
        raise HTTPException(error.status_code, detail={"code": error.code, "message": error.message}) from error
    if job is None:
        raise HTTPException(404, detail={"code": "GENERATION_JOB_NOT_FOUND", "message": "The generation job is unavailable."})
    return GenerationJobResponse.model_validate(job)


@router.get("/{job_id}/preview", response_model=GenerationPreviewResponse)
async def get_generation_preview(job_id: str, claims: CurrentAuthenticated, session: Session) -> GenerationPreviewResponse:
    job = await GenerationJobService(session).get(job_id, claims.user_id, is_admin=_is_admin(claims))
    if job is None or job.preview_id is None:
        raise HTTPException(404, detail={"code": "GENERATION_PREVIEW_NOT_FOUND", "message": "The generation preview is unavailable."})
    factory: AsyncpgPoolFactory | None = None
    try:
        settings = Settings()
        if not settings.ai_postgres_dsn:
            raise RuntimeError("AI PostgreSQL is not configured")
        factory = AsyncpgPoolFactory(settings.ai_postgres_dsn)
        pool = await factory.open()
        repository = AIMemoryRepository(pool)
        await repository.setup_schema()
        preview = await repository.get_preview(job.user_id, job.preview_id)
    except Exception as error:
        raise HTTPException(503, detail={"code": "AI_PREVIEW_UNAVAILABLE", "message": "AI preview storage is unavailable."}) from error
    finally:
        if factory is not None:
            await factory.close()
    if preview is None:
        raise HTTPException(404, detail={"code": "GENERATION_PREVIEW_NOT_FOUND", "message": "The generation preview is unavailable."})
    response = dict(preview)
    response["target_itinerary_id"] = job.target_itinerary_id
    response["base_version"] = job.request_json.get("base_version")
    return GenerationPreviewResponse.model_validate(response)


@router.post("/{job_id}/preview/{preview_id}:apply", response_model=OperationResponse)
async def apply_generation_preview(
    job_id: str,
    preview_id: str,
    claims: CurrentConsumer,
    session: Session,
    if_match_version: Annotated[int, Header(alias="If-Match-Version", ge=1)],
    operation_id: Annotated[str, Header(alias="X-Operation-ID", min_length=1, max_length=128)],
) -> OperationResponse:
    job = await GenerationJobService(session).get(job_id, claims.user_id)
    if job is None or job.preview_id != preview_id or job.target_itinerary_id is None:
        raise HTTPException(404, detail={"code": "GENERATION_PREVIEW_NOT_FOUND", "message": "The generation preview is unavailable."})
    factory: AsyncpgPoolFactory | None = None
    try:
        settings = Settings()
        if not settings.ai_postgres_dsn:
            raise RuntimeError("AI PostgreSQL is not configured")
        factory = AsyncpgPoolFactory(settings.ai_postgres_dsn)
        pool = await factory.open()
        repository = AIMemoryRepository(pool)
        await repository.setup_schema()
        preview = await repository.get_preview(claims.user_id, preview_id)
    except Exception as error:
        raise HTTPException(503, detail={"code": "AI_PREVIEW_UNAVAILABLE", "message": "AI preview storage is unavailable."}) from error
    finally:
        if factory is not None:
            await factory.close()
    if preview is None or not isinstance(preview.get("draft"), dict):
        raise HTTPException(404, detail={"code": "GENERATION_PREVIEW_NOT_FOUND", "message": "The generation preview is unavailable."})
    try:
        result = await ItineraryService(session).apply_operation(
            job.target_itinerary_id,
            claims.user_id,
            base_version=if_match_version,
            operation_id=operation_id,
            operation_type="apply_ai_preview",
            payload={
                "preview_id": preview_id,
                "generation_job_id": job.id,
                "draft": preview["draft"],
                "base_version": job.request_json.get("base_version"),
            },
        )
    except ValueError as error:
        raise HTTPException(422, detail={"code": "PREVIEW_INVALID", "message": str(error)}) from error
    return OperationResponse.model_validate(result.__dict__)
