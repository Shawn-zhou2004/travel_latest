from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.modules.admin.knowledge_governance import derive_next_review_at, validate_source_version
from app.modules.admin.models import (
    AdminAction,
    CommunityKnowledgeReview,
    ExternalWebKnowledgeSource,
    OfficialKnowledgeSource,
    PoiCandidate,
    PoiKnowledgeImportJob,
    StructuredKnowledgeImportJob,
    SearchIndexRebuildJob,
    WebKnowledgeCandidate,
    WebKnowledgeSearchJob,
)
from app.modules.admin.schemas import (
    ExternalWebKnowledgeSourceDecision,
    ExternalWebKnowledgeSourceResponse,
    CommunityKnowledgeReviewDecision,
    CommunityKnowledgeReviewResponse,
    WebKnowledgeCandidateDecision,
    WebKnowledgeCandidateResponse,
    WebKnowledgeSearchJobCreate,
    WebKnowledgeSearchJobResponse,
    SearchIndexInventoryResponse,
    SearchIndexRebuildCreate,
    SearchIndexRebuildJobResponse,
    AdminUserPage,
    AdminUserResponse,
    AdminUserUpdate,
    PoiCandidateDecision,
    PoiCandidateResponse,
)
from app.modules.admin.users import list_admin_users, update_admin_user
from app.modules.admin.search_indexes import SearchIndexInventoryService, queue_rebuild_job, rebuild_job_item
from app.core.settings import Settings
from app.modules.auth.dependencies import CurrentAdmin
from app.modules.ai_rag.catalog import DomainRetrievalRequest
from app.modules.ai_rag.types import Citation, KnowledgeDomain, RagStatus
from app.modules.ai_workflows.models import GenerationJob
from app.modules.ai_workflows.runtime import open_domain_retrieval_runtime
from app.modules.community.models import CompanionRequest, ContentReport, Post
from app.modules.exports.models import ExportTask
from app.modules.community.service import CommunityError, CommunityService
from app.modules.orders.models import TravelOrder
from app.modules.providers.schemas import ProviderDecision
from app.modules.providers.service import ProviderError, ProviderService
from app.workers.health import WORKER_HEARTBEAT_KEY, worker_heartbeat_status
from redis.asyncio import Redis


router = APIRouter(prefix="/admin", tags=["admin"])
Session = Annotated[AsyncSession, Depends(get_session)]


class Page(BaseModel):
    items: list[dict]
    next_cursor: None = None


class Decision(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    moderation_reason: str | None = Field(default=None, max_length=500)
    review_reason: str | None = Field(default=None, max_length=500)
    resolution: str | None = Field(default=None, max_length=500)

    def reason(self) -> str:
        return (self.moderation_reason or self.review_reason or self.resolution or "").strip()


class OfficialKnowledgeCreate(BaseModel):
    source_type: Literal["rule", "template", "poi"]
    title: str = Field(min_length=1, max_length=160)
    body_text: str = Field(min_length=1, max_length=20000)
    city_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    poi_id: str | None = Field(default=None, max_length=128)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)


class OfficialKnowledgeDecision(BaseModel):
    status: Literal["indexed", "rejected", "inactive"]
    reason: str = Field(min_length=1, max_length=500)


class PoiKnowledgeImportCreate(BaseModel):
    city_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    keywords: list[str] = Field(min_length=1, max_length=20)

    def model_post_init(self, __context: object) -> None:
        normalized = list(dict.fromkeys(item.strip() for item in self.keywords if item.strip()))
        if not normalized:
            raise ValueError("At least one POI keyword is required.")
        if any(len(item) > 100 for item in normalized):
            raise ValueError("Each POI keyword must be at most 100 characters.")
        self.keywords = normalized


class StructuredKnowledgeImportEntry(BaseModel):
    source_type: Literal["rule", "template"]
    title: str = Field(min_length=1, max_length=160)
    body_text: str = Field(min_length=1, max_length=20000)


class StructuredKnowledgeImportCreate(BaseModel):
    city_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    entries: list[StructuredKnowledgeImportEntry] = Field(min_length=1, max_length=50)

    def model_post_init(self, __context: object) -> None:
        normalized: list[StructuredKnowledgeImportEntry] = []
        seen: set[tuple[str, str, str]] = set()
        for entry in self.entries:
            entry.title = entry.title.strip()
            entry.body_text = entry.body_text.strip()
            key = (entry.source_type, entry.title, entry.body_text)
            if entry.title and entry.body_text and key not in seen:
                normalized.append(entry)
                seen.add(key)
        if not normalized:
            raise ValueError("At least one rule or template entry is required.")
        self.entries = normalized


class RetrievalPreviewCreate(BaseModel):
    city_code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    query: str = Field(min_length=1, max_length=2000)


class RetrievalPreviewCitation(BaseModel):
    document_id: str
    chunk_id: str
    source_type: str
    source_id: str
    city_code: str | None
    poi_id: str | None
    source_updated_at: datetime


class RetrievalPreviewContext(BaseModel):
    rank: int
    score: float
    content: str
    citation: RetrievalPreviewCitation


class RetrievalPreviewResponse(BaseModel):
    status: RagStatus
    message: str | None = None
    contexts: list[RetrievalPreviewContext] = Field(default_factory=list)


class AiWorkflowCategoryHealth(BaseModel):
    queued: int
    running: int
    failed: int
    most_recent_at: datetime | None


class AiOutboxHealth(BaseModel):
    unprocessed: int
    retrying: int
    dead_letter: int
    most_recent_at: datetime | None


class WorkerHeartbeatHealth(BaseModel):
    status: Literal["healthy", "stale", "unavailable"]
    last_heartbeat_at: datetime | None


class AiWorkflowHealthResponse(BaseModel):
    generation_jobs: AiWorkflowCategoryHealth
    export_tasks: AiWorkflowCategoryHealth
    outbox: AiOutboxHealth
    worker: WorkerHeartbeatHealth


async def _worker_heartbeat_health(settings: Settings | None = None) -> WorkerHeartbeatHealth:
    settings = settings or Settings()
    if settings.app_env == "test" or not settings.redis_url:
        return WorkerHeartbeatHealth(status="unavailable", last_heartbeat_at=None)
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        value = await redis.get(WORKER_HEARTBEAT_KEY)
    except Exception:
        return WorkerHeartbeatHealth(status="unavailable", last_heartbeat_at=None)
    finally:
        await redis.aclose()
    status, heartbeat_at = worker_heartbeat_status(value)
    return WorkerHeartbeatHealth(status=status, last_heartbeat_at=heartbeat_at)


def _require_admin(claims: CurrentAdmin) -> None:
    if "platform_admin" not in claims.roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Platform admin role required."})


def _record(session: AsyncSession, claims: CurrentAdmin, action: str, target_type: str, target_id: str, reason: str, result: dict) -> None:
    session.add(AdminAction(actor_id=claims.user_id, action=action, target_type=target_type, target_id=target_id, reason=reason, result_json=result))


@router.get("/posts", response_model=Page)
async def list_posts(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(Post).order_by(Post.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(Post.status == status)
    posts = (await session.scalars(statement)).all()
    return Page(items=[{"id": post.id, "author_id": post.author_id, "content_type": post.content_type, "title": post.title, "body": post.body_text, "status": post.status, "moderation_reason": post.moderation_reason, "has_route_snapshot": post.content_type == "itinerary" and isinstance(post.itinerary_snapshot_json, dict), "created_at": post.created_at, "updated_at": post.updated_at} for post in posts])


@router.get("/search-indexes", response_model=SearchIndexInventoryResponse)
async def list_search_indexes(claims: CurrentAdmin) -> SearchIndexInventoryResponse:
    _require_admin(claims)
    return SearchIndexInventoryResponse(items=await SearchIndexInventoryService(Settings()).inventory())


@router.post("/search-indexes:rebuild", response_model=SearchIndexRebuildJobResponse, status_code=201)
async def rebuild_search_index(body: SearchIndexRebuildCreate, claims: CurrentAdmin, session: Session, response: Response) -> SearchIndexRebuildJobResponse:
    _require_admin(claims)
    try:
        job, created = await queue_rebuild_job(session, claims, body.index_name)
    except ValueError as error:
        raise HTTPException(422, detail={"code": "SEARCH_INDEX_NOT_ALLOWED", "message": str(error)}) from error
    await session.commit()
    if not created:
        response.status_code = 200
    return SearchIndexRebuildJobResponse(**rebuild_job_item(job))


@router.get("/search-index-rebuild-jobs/{job_id}", response_model=SearchIndexRebuildJobResponse)
async def get_search_index_rebuild_job(job_id: str, claims: CurrentAdmin, session: Session) -> SearchIndexRebuildJobResponse:
    _require_admin(claims)
    job = await session.get(SearchIndexRebuildJob, job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "SEARCH_INDEX_REBUILD_JOB_NOT_FOUND", "message": "The rebuild job is unavailable."})
    return SearchIndexRebuildJobResponse(**rebuild_job_item(job))


@router.get("/users", response_model=AdminUserPage)
async def list_users(
    claims: CurrentAdmin,
    session: Session,
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=500),
) -> AdminUserPage:
    _require_admin(claims)
    return await list_admin_users(session, query, limit, cursor)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(user_id: str, body: AdminUserUpdate, claims: CurrentAdmin, session: Session) -> AdminUserResponse:
    _require_admin(claims)
    user = await update_admin_user(session, user_id, body)
    _record(
        session,
        claims,
        "user.updated",
        "user",
        user.id,
        "Updated user status and unscoped roles.",
        {"status": user.status, "roles": user.roles},
    )
    await session.commit()
    return user


@router.patch("/posts/{post_id}")
async def decide_post(post_id: str, body: Decision, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    reason = body.reason()
    if not reason:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "A moderation reason is required."})
    try:
        service = CommunityService(session)
        if body.status == "published":
            post = await service.publish(post_id, claims.user_id, reason, is_admin=True)
        elif body.status == "rejected":
            post = await service.reject(post_id, claims.user_id, reason)
        elif body.status == "hidden":
            post = await service.hide(post_id, claims.user_id, reason)
        else:
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Unsupported post decision."})
    except CommunityError as error:
        raise HTTPException(409, detail={"code": error.code, "message": error.message}) from error
    _record(session, claims, f"post.{post.status}", "post", post.id, reason, {"status": post.status})
    await session.commit()
    return {"id": post.id, "status": post.status, "moderation_reason": post.moderation_reason}


@router.get("/companion-requests", response_model=Page)
async def list_companion_requests(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(CompanionRequest).order_by(CompanionRequest.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(CompanionRequest.review_status == status)
    records = (await session.scalars(statement)).all()
    return Page(items=[{
        "id": item.id, "owner_id": item.owner_id, "title": item.title,
        "destination": item.city_code or "", "trip_kind": item.trip_kind,
        "has_itinerary": item.itinerary_id is not None, "start_date": item.start_date,
        "end_date": item.end_date, "party_size": item.party_size,
        "accepted_count": item.accepted_count, "travel_pace": item.travel_pace,
        "interest_tags": item.interest_tags or [], "intro_text": item.intro_text,
        "description": item.description, "business_status": item.status,
        "status": item.review_status, "review_reason": item.review_reason,
        "created_at": item.created_at,
    } for item in records])


@router.patch("/companion-requests/{request_id}")
async def decide_companion_request(request_id: str, body: Decision, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    reason = body.reason()
    if body.status not in {"approved", "rejected"} or not reason:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "A supported decision and review reason are required."})
    item = await session.get(CompanionRequest, request_id)
    if item is None or item.review_status != "pending_review":
        raise HTTPException(409, detail={"code": "INVALID_COMPANION_TRANSITION", "message": "This companion request cannot be reviewed."})
    item.review_status, item.review_reason = body.status, reason
    if body.status == "rejected":
        item.status = "cancelled"
    _record(session, claims, f"companion_request.{body.status}", "companion_request", item.id, reason, {"review_status": item.review_status})
    await session.commit()
    return {"id": item.id, "status": item.review_status, "review_reason": item.review_reason}


@router.get("/reports", response_model=Page)
async def list_reports(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(ContentReport).order_by(ContentReport.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(ContentReport.status == status)
    reports = (await session.scalars(statement)).all()
    return Page(items=[{"id": report.id, "reporter_id": report.reporter_id, "target_type": report.target_type, "target_id": report.target_id, "reason": report.reason_code, "details": report.detail, "status": report.status, "resolution": report.resolution, "created_at": report.created_at} for report in reports])


@router.patch("/reports/{report_id}")
async def decide_report(report_id: str, body: Decision, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    reason = body.reason()
    if body.status not in {"resolved", "dismissed"} or not reason:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "A supported decision and resolution are required."})
    report = await session.get(ContentReport, report_id)
    if report is None or report.status != "pending":
        raise HTTPException(409, detail={"code": "INVALID_REPORT_TRANSITION", "message": "This report cannot be decided."})
    report.status, report.resolution = body.status, reason
    _record(session, claims, f"report.{body.status}", "content_report", report.id, reason, {"status": report.status})
    await session.commit()
    return {"id": report.id, "status": report.status, "resolution": report.resolution}


@router.get("/travel-orders", response_model=Page)
async def list_orders(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(TravelOrder).order_by(TravelOrder.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(TravelOrder.status == status)
    orders = (await session.scalars(statement)).all()
    return Page(items=[{"id": order.id, "order_no": order.order_no, "amount": str(order.amount), "currency": order.currency, "status": order.status, "payment_status": order.payment_status, "fulfillment_status": order.fulfillment_status, "failure_code": order.failure_code, "created_at": order.created_at} for order in orders])


def _provider_error(error: ProviderError) -> HTTPException:
    status_code = 403 if error.code == "FORBIDDEN" else 404 if error.code == "PROVIDER_NOT_FOUND" else 409
    return HTTPException(status_code, detail={"code": error.code, "message": error.message})


@router.get("/providers", response_model=Page)
async def list_providers(claims: CurrentAdmin, session: Session, status: str | None = None) -> Page:
    _require_admin(claims)
    try:
        providers = await ProviderService(session).list_provider_applications(claims.roles, status)
    except ProviderError as error:
        raise _provider_error(error) from error
    return Page(items=[{"id": provider.id, "provider_type": provider.provider_type, "legal_name": provider.legal_name, "contact_masked": provider.contact[:3] + "***", "verification_status": provider.status, "review_reason": provider.review_reason, "member_count": 0, "created_at": provider.created_at} for provider in providers])


@router.patch("/providers/{provider_id}")
async def decide_provider(provider_id: str, body: ProviderDecision, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    try:
        provider = await ProviderService(session).review(
            provider_id, claims.user_id, claims.roles, body.status, body.review_reason
        )
    except ProviderError as error:
        raise _provider_error(error) from error
    _record(
        session,
        claims,
        f"provider.{provider.status}",
        "provider",
        provider.id,
        body.review_reason,
        {"verification_status": provider.status},
    )
    await session.commit()
    return {"id": provider.id, "verification_status": provider.status, "review_reason": provider.review_reason}


def _knowledge_item(item: OfficialKnowledgeSource) -> dict:
    return {
        "id": item.id,
        "source_type": item.source_type,
        "title": item.title,
        "body_text": item.body_text,
        "city_code": item.city_code,
        "poi_id": item.poi_id,
        "language": item.language,
        "status": item.status,
        "review_reason": item.review_reason,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": item.reviewed_at,
        "indexed_at": item.indexed_at,
        "index_error": item.index_error,
        "removal_error": item.removal_error,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("/ai/metrics", response_model=dict)
async def get_ai_metrics(claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    generation_rows = (await session.execute(
        select(GenerationJob.status, func.count(GenerationJob.id)).group_by(GenerationJob.status)
    )).all()
    knowledge_rows = (await session.execute(
        select(OfficialKnowledgeSource.status, func.count(OfficialKnowledgeSource.id)).group_by(OfficialKnowledgeSource.status)
    )).all()
    poi_import_rows = (await session.execute(
        select(PoiKnowledgeImportJob.status, func.count(PoiKnowledgeImportJob.id)).group_by(PoiKnowledgeImportJob.status)
    )).all()
    structured_import_rows = (await session.execute(
        select(StructuredKnowledgeImportJob.status, func.count(StructuredKnowledgeImportJob.id)).group_by(StructuredKnowledgeImportJob.status)
    )).all()
    generation_by_status = {status: count for status, count in generation_rows}
    knowledge_by_status = {status: count for status, count in knowledge_rows}
    return {
        "generation": {
            "total": sum(generation_by_status.values()),
            "failed": generation_by_status.get("failed", 0),
            "awaiting_confirmation": generation_by_status.get("awaiting_confirmation", 0),
        },
        "knowledge": {
            "indexed": knowledge_by_status.get("indexed", 0),
            "failed": knowledge_by_status.get("failed", 0),
            "pending_review": knowledge_by_status.get("pending_review", 0),
            "indexing": knowledge_by_status.get("indexing", 0),
        },
        "imports": {
            "poi_failed": dict(poi_import_rows).get("failed", 0),
            "structured_failed": dict(structured_import_rows).get("failed", 0),
        },
    }


@router.get("/ai/workflow-health", response_model=AiWorkflowHealthResponse)
async def get_ai_workflow_health(claims: CurrentAdmin, session: Session) -> AiWorkflowHealthResponse:
    _require_admin(claims)
    generation = (await session.execute(select(
        func.coalesce(func.sum(case((GenerationJob.status == "queued", 1), else_=0)), 0),
        func.coalesce(func.sum(case((GenerationJob.status.in_(("understanding", "retrieving", "planning", "validating")), 1), else_=0)), 0),
        func.coalesce(func.sum(case((GenerationJob.status == "failed", 1), else_=0)), 0),
        func.max(GenerationJob.updated_at),
    ))).one()
    exports = (await session.execute(select(
        func.coalesce(func.sum(case((ExportTask.status == "queued", 1), else_=0)), 0),
        func.coalesce(func.sum(case((ExportTask.status == "running", 1), else_=0)), 0),
        func.coalesce(func.sum(case((ExportTask.status == "failed", 1), else_=0)), 0),
        func.max(ExportTask.updated_at),
    ))).one()
    outbox = (await session.execute(select(
        func.coalesce(func.sum(case(((OutboxEvent.published_at.is_(None)) & (OutboxEvent.retry_count == 0), 1), else_=0)), 0),
        func.coalesce(func.sum(case(((OutboxEvent.published_at.is_(None)) & (OutboxEvent.retry_count > 0), 1), else_=0)), 0),
        func.max(OutboxEvent.updated_at),
    ))).one()
    return AiWorkflowHealthResponse(
        generation_jobs=AiWorkflowCategoryHealth(queued=generation[0], running=generation[1], failed=generation[2], most_recent_at=generation[3]),
        export_tasks=AiWorkflowCategoryHealth(queued=exports[0], running=exports[1], failed=exports[2], most_recent_at=exports[3]),
        # Dead-letter delivery happens at the broker and has no persisted outbox state.
        outbox=AiOutboxHealth(unprocessed=outbox[0], retrying=outbox[1], dead_letter=0, most_recent_at=outbox[2]),
        worker=await _worker_heartbeat_health(),
    )


def _retrieval_preview_citation(citation: Citation) -> RetrievalPreviewCitation:
    return RetrievalPreviewCitation(
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        source_type=citation.source_type.value,
        source_id=citation.source_id,
        city_code=citation.city_code,
        poi_id=citation.poi_id,
        source_updated_at=citation.source_updated_at,
    )


@router.post("/ai/retrieval-preview", response_model=RetrievalPreviewResponse)
async def preview_ai_retrieval(body: RetrievalPreviewCreate, claims: CurrentAdmin) -> RetrievalPreviewResponse:
    _require_admin(claims)
    try:
        runtime = await open_domain_retrieval_runtime()
    except Exception as error:
        raise HTTPException(
            503,
            detail={
                "code": "AI_RETRIEVAL_UNAVAILABLE",
                "message": "AI retrieval is unavailable for this probe.",
            },
        ) from error

    try:
        result = await runtime.catalog.retrieve(
            DomainRetrievalRequest(
                domain=KnowledgeDomain.OFFICIAL,
                query=body.query,
                city_code=body.city_code,
            )
        )
    except Exception as error:
        raise HTTPException(
            503,
            detail={
                "code": "AI_RETRIEVAL_UNAVAILABLE",
                "message": "AI retrieval is unavailable for this probe.",
            },
        ) from error
    finally:
        await runtime.close()

    return RetrievalPreviewResponse(
        status=result.status,
        message=result.message,
        contexts=[
            RetrievalPreviewContext(
                rank=rank,
                score=context.score,
                content=context.content,
                citation=_retrieval_preview_citation(context.citation),
            )
            for rank, context in enumerate(result.contexts, start=1)
        ],
    )


@router.get("/ai/knowledge-sources", response_model=Page)
async def list_official_knowledge_sources(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(OfficialKnowledgeSource).order_by(OfficialKnowledgeSource.updated_at.desc()).limit(limit)
    if status:
        statement = statement.where(OfficialKnowledgeSource.status == status)
    records = (await session.scalars(statement)).all()
    return Page(items=[_knowledge_item(item) for item in records])


@router.post("/ai/knowledge-sources", response_model=dict, status_code=201)
async def create_official_knowledge_source(body: OfficialKnowledgeCreate, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    item = OfficialKnowledgeSource(**body.model_dump(), status="pending_review")
    session.add(item)
    await session.flush()
    _record(session, claims, "ai_knowledge_source.created", "official_knowledge_source", item.id, "Submitted for review.", {"status": item.status})
    await session.commit()
    return _knowledge_item(item)


@router.patch("/ai/knowledge-sources/{source_id}", response_model=dict)
async def decide_official_knowledge_source(source_id: str, body: OfficialKnowledgeDecision, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    item = await session.get(OfficialKnowledgeSource, source_id)
    if item is None:
        raise HTTPException(404, detail={"code": "KNOWLEDGE_SOURCE_NOT_FOUND", "message": "The knowledge source is unavailable."})
    if body.status == "inactive":
        if item.status == "indexed":
            item.status = "removing"
            item.removal_error = None
            session.add(OutboxEvent(
                event_type="ai.official_knowledge_removal_requested",
                aggregate_type="official_knowledge_source",
                aggregate_id=item.id,
                trace_id=new_uuid(),
                payload_json={"knowledge_source_id": item.id},
            ))
        elif item.status in {"draft", "pending_review", "rejected", "failed", "inactive"}:
            item.status = "inactive"
        else:
            raise HTTPException(409, detail={"code": "KNOWLEDGE_SOURCE_REMOVAL_NOT_ALLOWED", "message": "This knowledge source is already being indexed or removed."})
    elif body.status == "rejected":
        if item.status != "pending_review":
            raise HTTPException(409, detail={"code": "KNOWLEDGE_SOURCE_REVIEW_NOT_ALLOWED", "message": "Only pending knowledge sources can be rejected."})
        item.status = "rejected"
    else:
        if item.status not in {"pending_review", "failed"}:
            raise HTTPException(409, detail={"code": "KNOWLEDGE_SOURCE_INDEX_NOT_ALLOWED", "message": "Only pending or failed knowledge sources can be indexed."})
        try:
            validate_source_version(
                item.source_version,
                document_id=item.id,
                supersedes_document_id=item.supersedes_document_id,
            )
        except ValueError as error:
            raise HTTPException(
                409,
                detail={"code": "KNOWLEDGE_SOURCE_GOVERNANCE_INVALID", "message": str(error)},
            ) from error
        reviewed_at = utc_now()
        item.status = "indexing"
        item.index_error = None
        item.reviewed_at = reviewed_at
        item.next_review_at = derive_next_review_at(item.source_type, reviewed_at)
        session.add(OutboxEvent(
            event_type="ai.official_knowledge_index_requested",
            aggregate_type="official_knowledge_source",
            aggregate_id=item.id,
            trace_id=new_uuid(),
            payload_json={"knowledge_source_id": item.id},
        ))
    item.review_reason = body.reason
    item.reviewed_by = claims.user_id
    if body.status != "indexed":
        item.reviewed_at = utc_now()
    _record(session, claims, f"ai_knowledge_source.{item.status}", "official_knowledge_source", item.id, body.reason, {"status": item.status})
    await session.commit()
    return _knowledge_item(item)


def _import_job_item(job: PoiKnowledgeImportJob) -> dict:
    return {
        "id": job.id,
        "city_code": job.city_code,
        "keywords": job.keywords,
        "status": job.status,
        "imported_count": job.imported_count,
        "skipped_count": job.skipped_count,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _poi_candidate_item(candidate: PoiCandidate) -> PoiCandidateResponse:
    return PoiCandidateResponse(
        id=candidate.id,
        poi_id=candidate.poi_id,
        name=candidate.name,
        address=candidate.address,
        city_code=candidate.city_code,
        longitude=candidate.longitude,
        latitude=candidate.latitude,
        amap_type=candidate.amap_type,
        tags=candidate.tags,
        status=candidate.status,
        admin_weight=candidate.admin_weight,
        discovery_count=candidate.discovery_count,
        confirmed_itinerary_count=candidate.confirmed_itinerary_count,
        review_reason=candidate.review_reason,
        reviewed_by=candidate.reviewed_by,
        reviewed_at=candidate.reviewed_at,
        official_knowledge_source_id=candidate.official_knowledge_source_id,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


@router.get("/ai/poi-candidates", response_model=Page)
async def list_poi_candidates(
    claims: CurrentAdmin,
    session: Session,
    status: str | None = None,
    city_code: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> Page:
    _require_admin(claims)
    statement = select(PoiCandidate).order_by(
        PoiCandidate.admin_weight.desc(),
        PoiCandidate.confirmed_itinerary_count.desc(),
        PoiCandidate.discovery_count.desc(),
        PoiCandidate.updated_at.desc(),
        PoiCandidate.poi_id.asc(),
    ).limit(limit)
    if status:
        statement = statement.where(PoiCandidate.status == status)
    if city_code:
        statement = statement.where(PoiCandidate.city_code == city_code)
    candidates = (await session.scalars(statement)).all()
    return Page(items=[_poi_candidate_item(candidate).model_dump() for candidate in candidates])


@router.patch("/ai/poi-candidates/{candidate_id}", response_model=PoiCandidateResponse)
async def decide_poi_candidate(
    candidate_id: str,
    body: PoiCandidateDecision,
    claims: CurrentAdmin,
    session: Session,
) -> PoiCandidateResponse:
    _require_admin(claims)
    candidate = await session.get(PoiCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, detail={"code": "POI_CANDIDATE_NOT_FOUND", "message": "The POI candidate is unavailable."})
    if body.status in {"approved", "rejected"} and candidate.status != "pending_review":
        raise HTTPException(409, detail={"code": "POI_CANDIDATE_REVIEW_NOT_ALLOWED", "message": "Only pending POI candidates can be reviewed."})
    if body.status == "retired" and candidate.status != "approved":
        raise HTTPException(409, detail={"code": "POI_CANDIDATE_RETIRE_NOT_ALLOWED", "message": "Only approved POI candidates can be retired."})

    candidate.status = body.status
    candidate.tags = body.tags if body.status == "approved" else candidate.tags
    candidate.admin_weight = body.admin_weight if body.status == "approved" else candidate.admin_weight
    candidate.review_reason = body.reason
    candidate.reviewed_by = claims.user_id
    candidate.reviewed_at = utc_now()

    if body.status == "approved" and candidate.official_knowledge_source_id is None:
        source = OfficialKnowledgeSource(
            source_type="poi",
            title=candidate.name,
            body_text=(
                f"Verified AMap attraction: {candidate.name}. Address: {candidate.address}. "
                f"POI ID: {candidate.poi_id}. Approved travel tags: {', '.join(candidate.tags)}."
            ),
            city_code=candidate.city_code,
            poi_id=candidate.poi_id,
            language="zh-CN",
            status="pending_review",
            review_reason="Created from an administrator-approved POI candidate.",
        )
        session.add(source)
        await session.flush()
        candidate.official_knowledge_source_id = source.id

    _record(
        session,
        claims,
        f"ai_poi_candidate.{candidate.status}",
        "poi_candidate",
        candidate.id,
        body.reason or "Approved POI candidate for curated recommendations.",
        {
            "status": candidate.status,
            "tags": candidate.tags,
            "admin_weight": candidate.admin_weight,
            "official_knowledge_source_id": candidate.official_knowledge_source_id,
        },
    )
    await session.commit()
    return _poi_candidate_item(candidate)


def _structured_import_job_item(job: StructuredKnowledgeImportJob) -> dict:
    return {
        "id": job.id,
        "city_code": job.city_code,
        "entries": job.entries,
        "status": job.status,
        "imported_count": job.imported_count,
        "skipped_count": job.skipped_count,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _websearch_job_item(job: WebKnowledgeSearchJob) -> WebKnowledgeSearchJobResponse:
    return WebKnowledgeSearchJobResponse(
        id=job.id,
        requested_by=job.requested_by,
        city_code=job.city_code,
        query=job.query,
        target_domain=job.target_domain,
        status=job.status,
        provider_name=job.provider_name,
        error_code=job.error_code,
        error_message=job.error_message,
        result_count=job.result_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _websearch_candidate_item(candidate: WebKnowledgeCandidate) -> WebKnowledgeCandidateResponse:
    return WebKnowledgeCandidateResponse(
        id=candidate.id,
        job_id=candidate.job_id,
        title=candidate.title,
        excerpt=candidate.excerpt,
        source_url=candidate.source_url,
        source_host=candidate.source_host,
        published_at=candidate.published_at,
        fetched_at=candidate.fetched_at,
        city_code=candidate.city_code,
        target_domain=candidate.target_domain,
        status=candidate.status,
        review_reason=candidate.review_reason,
        reviewed_by=candidate.reviewed_by,
        reviewed_at=candidate.reviewed_at,
        external_web_source_id=candidate.external_web_source_id,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def _external_web_knowledge_source_item(source: ExternalWebKnowledgeSource) -> ExternalWebKnowledgeSourceResponse:
    return ExternalWebKnowledgeSourceResponse(
        id=source.id,
        candidate_id=source.candidate_id,
        target_domain=source.target_domain,
        title=source.title,
        body_text=source.body_text,
        city_code=source.city_code,
        source_url=source.source_url,
        source_host=source.source_host,
        published_at=source.published_at,
        fetched_at=source.fetched_at,
        status=source.status,
        review_reason=source.review_reason,
        reviewed_by=source.reviewed_by,
        reviewed_at=source.reviewed_at,
        indexed_at=source.indexed_at,
        index_error=source.index_error,
        removal_error=source.removal_error,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _community_knowledge_review_item(review: CommunityKnowledgeReview, post: Post) -> CommunityKnowledgeReviewResponse:
    return CommunityKnowledgeReviewResponse(
        id=review.id,
        post_id=review.post_id,
        status=review.status,
        reason=review.reason,
        reviewed_by=review.reviewed_by,
        reviewed_at=review.reviewed_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
        post_title=post.title,
        post_body_text=post.body_text,
        post_city_code=post.city_code,
        post_status=post.status,
    )


@router.get("/ai/community-knowledge-reviews", response_model=Page)
async def list_community_knowledge_reviews(claims: CurrentAdmin, session: Session, status: str = "pending", limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    rows = (await session.execute(
        select(CommunityKnowledgeReview, Post)
        .join(Post, Post.id == CommunityKnowledgeReview.post_id)
        .where(CommunityKnowledgeReview.status == status)
        .order_by(CommunityKnowledgeReview.created_at.asc())
        .limit(limit)
    )).all()
    return Page(items=[_community_knowledge_review_item(review, post).model_dump() for review, post in rows])


@router.patch("/ai/community-knowledge-reviews/{post_id}", response_model=CommunityKnowledgeReviewResponse)
async def decide_community_knowledge_review(post_id: str, body: CommunityKnowledgeReviewDecision, claims: CurrentAdmin, session: Session) -> CommunityKnowledgeReviewResponse:
    _require_admin(claims)
    review = await session.scalar(select(CommunityKnowledgeReview).where(CommunityKnowledgeReview.post_id == post_id))
    if review is None:
        raise HTTPException(404, detail={"code": "COMMUNITY_KNOWLEDGE_REVIEW_NOT_FOUND", "message": "The community knowledge review is unavailable."})
    if review.status != "pending":
        raise HTTPException(409, detail={"code": "COMMUNITY_KNOWLEDGE_REVIEW_NOT_ALLOWED", "message": "Only pending community knowledge reviews can be decided."})
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(404, detail={"code": "POST_NOT_FOUND", "message": "The community post is unavailable."})

    review.status = body.status
    review.reason = body.reason
    review.reviewed_by = claims.user_id
    review.reviewed_at = utc_now()
    if body.status == "approved":
        session.add(OutboxEvent(
            event_type="ai.community_knowledge_index_requested",
            aggregate_type="community_knowledge_review",
            aggregate_id=review.id,
            trace_id=new_uuid(),
            payload_json={"post_id": post.id, "review_id": review.id},
        ))
    _record(
        session,
        claims,
        f"ai_community_knowledge_review.{review.status}",
        "community_knowledge_review",
        review.id,
        body.reason or "Approved for community knowledge indexing.",
        {"post_id": post.id, "status": review.status},
    )
    await session.commit()
    return _community_knowledge_review_item(review, post)


@router.post("/ai/websearch-jobs", response_model=WebKnowledgeSearchJobResponse, status_code=201)
async def create_websearch_job(body: WebKnowledgeSearchJobCreate, claims: CurrentAdmin, session: Session) -> WebKnowledgeSearchJobResponse:
    _require_admin(claims)
    job = WebKnowledgeSearchJob(requested_by=claims.user_id, **body.model_dump())
    session.add(job)
    await session.flush()
    session.add(OutboxEvent(
        event_type="ai.web_knowledge_search_requested",
        aggregate_type="web_knowledge_search_job",
        aggregate_id=job.id,
        trace_id=new_uuid(),
        payload_json={"job_id": job.id},
    ))
    _record(session, claims, "ai_websearch.queued", "web_knowledge_search_job", job.id, "Submitted web knowledge search.", {"target_domain": job.target_domain})
    await session.commit()
    return _websearch_job_item(job)


@router.get("/ai/websearch-jobs", response_model=Page)
async def list_websearch_jobs(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(WebKnowledgeSearchJob).order_by(WebKnowledgeSearchJob.updated_at.desc()).limit(limit)
    if status:
        statement = statement.where(WebKnowledgeSearchJob.status == status)
    jobs = (await session.scalars(statement)).all()
    return Page(items=[_websearch_job_item(job).model_dump() for job in jobs])


@router.get("/ai/websearch-jobs/{job_id}/candidates", response_model=Page)
async def list_websearch_candidates(job_id: str, claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    if await session.get(WebKnowledgeSearchJob, job_id) is None:
        raise HTTPException(404, detail={"code": "WEBSEARCH_JOB_NOT_FOUND", "message": "The web search job is unavailable."})
    statement = select(WebKnowledgeCandidate).where(WebKnowledgeCandidate.job_id == job_id).order_by(WebKnowledgeCandidate.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(WebKnowledgeCandidate.status == status)
    candidates = (await session.scalars(statement)).all()
    return Page(items=[_websearch_candidate_item(candidate).model_dump() for candidate in candidates])


@router.patch("/ai/websearch-candidates/{candidate_id}", response_model=WebKnowledgeCandidateResponse)
async def decide_websearch_candidate(candidate_id: str, body: WebKnowledgeCandidateDecision, claims: CurrentAdmin, session: Session) -> WebKnowledgeCandidateResponse:
    _require_admin(claims)
    candidate = await session.get(WebKnowledgeCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, detail={"code": "WEBSEARCH_CANDIDATE_NOT_FOUND", "message": "The web search candidate is unavailable."})
    if candidate.status != "needs_human_review":
        raise HTTPException(409, detail={"code": "WEBSEARCH_CANDIDATE_REVIEW_NOT_ALLOWED", "message": "Only candidates awaiting human review can be decided."})

    candidate.reviewed_by = claims.user_id
    candidate.reviewed_at = utc_now()
    if body.status == "rejected":
        candidate.status = "rejected"
        candidate.review_reason = body.reason
        _record(session, claims, "ai_websearch_candidate.rejected", "web_knowledge_candidate", candidate.id, body.reason or "", {"status": candidate.status})
    else:
        source = ExternalWebKnowledgeSource(
            candidate_id=candidate.id,
            target_domain=candidate.target_domain,
            title=body.title or "",
            body_text=body.body_text or "",
            city_code=candidate.city_code,
            source_url=candidate.source_url,
            source_host=candidate.source_host,
            published_at=candidate.published_at,
            fetched_at=candidate.fetched_at,
            status="pending_review",
        )
        session.add(source)
        await session.flush()
        candidate.status = "approved"
        candidate.external_web_source_id = source.id
        _record(session, claims, "ai_websearch_candidate.approved", "web_knowledge_candidate", candidate.id, "Approved external web knowledge source for review.", {"status": candidate.status, "external_web_source_id": source.id})
    await session.commit()
    return _websearch_candidate_item(candidate)


@router.get("/ai/external-web-knowledge-sources", response_model=Page)
async def list_external_web_knowledge_sources(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(ExternalWebKnowledgeSource).order_by(ExternalWebKnowledgeSource.updated_at.desc()).limit(limit)
    if status:
        statement = statement.where(ExternalWebKnowledgeSource.status == status)
    sources = (await session.scalars(statement)).all()
    return Page(items=[_external_web_knowledge_source_item(source).model_dump() for source in sources])


@router.patch("/ai/external-web-knowledge-sources/{source_id}", response_model=ExternalWebKnowledgeSourceResponse)
async def decide_external_web_knowledge_source(source_id: str, body: ExternalWebKnowledgeSourceDecision, claims: CurrentAdmin, session: Session) -> ExternalWebKnowledgeSourceResponse:
    _require_admin(claims)
    source = await session.get(ExternalWebKnowledgeSource, source_id)
    if source is None:
        raise HTTPException(404, detail={"code": "EXTERNAL_WEB_KNOWLEDGE_SOURCE_NOT_FOUND", "message": "The external web knowledge source is unavailable."})
    if source.status != "pending_review":
        raise HTTPException(409, detail={"code": "EXTERNAL_WEB_KNOWLEDGE_SOURCE_REVIEW_NOT_ALLOWED", "message": "Only pending external web knowledge sources can be reviewed."})

    source.reviewed_by = claims.user_id
    source.reviewed_at = utc_now()
    source.review_reason = body.reason
    if body.status == "rejected":
        source.status = "rejected"
    else:
        source.status = "indexing"
        source.index_error = None
        session.add(OutboxEvent(
            event_type="ai.external_web_knowledge_index_requested",
            aggregate_type="external_web_knowledge_source",
            aggregate_id=source.id,
            trace_id=new_uuid(),
            payload_json={"source_id": source.id},
        ))
    _record(session, claims, f"ai_external_web_knowledge_source.{source.status}", "external_web_knowledge_source", source.id, body.reason or "Approved for indexing.", {"status": source.status})
    await session.commit()
    return _external_web_knowledge_source_item(source)


@router.post("/ai/poi-import-jobs", response_model=dict, status_code=201)
async def create_poi_knowledge_import_job(body: PoiKnowledgeImportCreate, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    job = PoiKnowledgeImportJob(requested_by=claims.user_id, city_code=body.city_code, keywords=body.keywords)
    session.add(job)
    await session.flush()
    session.add(OutboxEvent(
        event_type="ai.poi_knowledge_import_requested",
        aggregate_type="poi_knowledge_import_job",
        aggregate_id=job.id,
        trace_id=new_uuid(),
        payload_json={"poi_knowledge_import_job_id": job.id},
    ))
    _record(session, claims, "ai_poi_import.queued", "poi_knowledge_import_job", job.id, "Submitted POI knowledge import.", {"city_code": job.city_code, "keywords": job.keywords})
    await session.commit()
    return _import_job_item(job)


@router.get("/ai/poi-import-jobs", response_model=Page)
async def list_poi_knowledge_import_jobs(claims: CurrentAdmin, session: Session, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    jobs = (await session.scalars(select(PoiKnowledgeImportJob).order_by(PoiKnowledgeImportJob.updated_at.desc()).limit(limit))).all()
    return Page(items=[_import_job_item(job) for job in jobs])


@router.post("/ai/poi-import-jobs/{job_id}/retry", response_model=dict)
async def retry_poi_knowledge_import_job(job_id: str, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    job = await session.get(PoiKnowledgeImportJob, job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "POI_IMPORT_JOB_NOT_FOUND", "message": "The POI import job is unavailable."})
    if job.status != "failed":
        raise HTTPException(409, detail={"code": "POI_IMPORT_RETRY_NOT_ALLOWED", "message": "Only failed POI import jobs can be retried."})
    job.status = "queued"
    job.imported_count = 0
    job.skipped_count = 0
    job.error_message = None
    session.add(OutboxEvent(
        event_type="ai.poi_knowledge_import_requested",
        aggregate_type="poi_knowledge_import_job",
        aggregate_id=job.id,
        trace_id=new_uuid(),
        payload_json={"poi_knowledge_import_job_id": job.id},
    ))
    _record(session, claims, "ai_poi_import.retried", "poi_knowledge_import_job", job.id, "Retried failed POI knowledge import.", {"status": job.status})
    await session.commit()
    return _import_job_item(job)


@router.post("/ai/structured-knowledge-import-jobs", response_model=dict, status_code=201)
async def create_structured_knowledge_import_job(body: StructuredKnowledgeImportCreate, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    entries = [entry.model_dump() for entry in body.entries]
    job = StructuredKnowledgeImportJob(requested_by=claims.user_id, city_code=body.city_code, entries=entries)
    session.add(job)
    await session.flush()
    session.add(OutboxEvent(
        event_type="ai.structured_knowledge_import_requested",
        aggregate_type="structured_knowledge_import_job",
        aggregate_id=job.id,
        trace_id=new_uuid(),
        payload_json={"structured_knowledge_import_job_id": job.id},
    ))
    _record(session, claims, "ai_structured_knowledge_import.queued", "structured_knowledge_import_job", job.id, "Submitted reviewed rules and templates for import.", {"city_code": job.city_code, "entry_count": len(entries)})
    await session.commit()
    return _structured_import_job_item(job)


@router.get("/ai/structured-knowledge-import-jobs", response_model=Page)
async def list_structured_knowledge_import_jobs(claims: CurrentAdmin, session: Session, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    jobs = (await session.scalars(select(StructuredKnowledgeImportJob).order_by(StructuredKnowledgeImportJob.updated_at.desc()).limit(limit))).all()
    return Page(items=[_structured_import_job_item(job) for job in jobs])


@router.post("/ai/structured-knowledge-import-jobs/{job_id}/retry", response_model=dict)
async def retry_structured_knowledge_import_job(job_id: str, claims: CurrentAdmin, session: Session) -> dict:
    _require_admin(claims)
    job = await session.get(StructuredKnowledgeImportJob, job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "STRUCTURED_KNOWLEDGE_IMPORT_JOB_NOT_FOUND", "message": "The structured knowledge import job is unavailable."})
    if job.status != "failed":
        raise HTTPException(409, detail={"code": "STRUCTURED_KNOWLEDGE_IMPORT_RETRY_NOT_ALLOWED", "message": "Only failed structured knowledge import jobs can be retried."})
    job.status = "queued"
    job.imported_count = 0
    job.skipped_count = 0
    job.error_message = None
    session.add(OutboxEvent(
        event_type="ai.structured_knowledge_import_requested",
        aggregate_type="structured_knowledge_import_job",
        aggregate_id=job.id,
        trace_id=new_uuid(),
        payload_json={"structured_knowledge_import_job_id": job.id},
    ))
    _record(session, claims, "ai_structured_knowledge_import.retried", "structured_knowledge_import_job", job.id, "Retried failed structured knowledge import.", {"status": job.status})
    await session.commit()
    return _structured_import_job_item(job)


@router.get("/ai/generation-jobs", response_model=Page)
async def list_generation_jobs(claims: CurrentAdmin, session: Session, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> Page:
    _require_admin(claims)
    statement = select(GenerationJob).order_by(GenerationJob.updated_at.desc()).limit(limit)
    if status:
        statement = statement.where(GenerationJob.status == status)
    jobs = (await session.scalars(statement)).all()
    return Page(items=[{
        "id": job.id, "city_code": job.city_code, "status": job.status, "progress": job.progress,
        "outcome": job.outcome, "error_code": job.error_code, "message": job.message,
        "preview_id": job.preview_id, "created_at": job.created_at, "updated_at": job.updated_at,
    } for job in jobs])
