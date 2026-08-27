"""First-wave event handlers registered by the Worker.

Handlers keep projections conservative until their owning domain adds a full
external integration. Each handler runs inside the consumer transaction.
"""

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.events.consumer import registered_routes
from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.models.user import UserSettings
from app.core.settings import Settings
from app.modules.ai_workflows.contracts import GenerationRequest
from app.modules.ai_workflows.models import GenerationJob
from app.modules.ai_workflows.runtime import open_ai_runtime, open_domain_retrieval_runtime
from app.modules.ai_workflows.service import GenerationJobService
from app.modules.ai_workflows.workflow import (
    ConstraintViolation,
    DependencyUnavailable,
    DraftSchemaError,
    InsufficientVerifiedCandidates,
    RequestValidationError,
)
from app.modules.ai_rag.types import AuthorityLevel, KnowledgeDomain, KnowledgeSourceType, ReviewedKnowledgeDocument
from app.modules.admin.knowledge_governance import derive_next_review_at, validate_source_version
from app.modules.admin.models import (
    CommunityKnowledgeReview,
    ExternalWebKnowledgeSource,
    OfficialKnowledgeSource,
    PoiCandidate,
    PoiKnowledgeImportJob,
    StructuredKnowledgeImportJob,
    SearchIndexRebuildJob,
)
from app.modules.admin.models import WebKnowledgeCandidate, WebKnowledgeSearchJob
from app.modules.community.models import Post
from app.modules.maps.service import AMapService, MapUnavailable
from app.modules.media.service import MEDIA_UPLOAD_CLEANUP_EVENT, expire_pending_uploads
from app.integrations.object_storage import S3ObjectStorage, StorageUnavailable
from app.modules.exports.renderer import render_docx
from app.modules.exports.service import (
    EXPORT_COMPLETED_EVENT,
    EXPORT_EXPIRATION_CLEANUP_EVENT,
    EXPORT_REQUESTED_EVENT,
    ExportTaskService,
    expire_succeeded_exports,
)
from app.modules.notifications.models import Notification
from app.modules.itineraries.service import ItineraryService
from app.modules.search.models import SearchProjection
from app.integrations.suppliers.client import SupplierAdapter, UnavailableSupplierAdapter
from app.modules.orders.models import MockTransportTicket
from app.modules.orders.services import FulfillmentService, MockTicketService, RefundService, SupplierFulfillmentUnavailable
from app.integrations.alipay import get_alipay_adapter
from app.integrations.suppliers.mock_transport import DeterministicMockTransportTicketIssuer
from app.integrations.mcp.transport import (
    MagicFlightOfferProvider,
    MagicMcpTransportConfig,
    MagicTrainOfferProvider,
    TransportOfferProvider,
    UnavailableFlightOfferProvider,
    UnavailableTrainOfferProvider,
)
from app.integrations.mcp.websearch import MagicMcpWebSearchProvider, is_knowledge_candidate_eligible
from hashlib import sha256
import httpx


# The authorized fulfillment adapter is supplied by the deployment integration.
# The default intentionally causes broker retry rather than a fictitious booking.
fulfillment_supplier: SupplierAdapter = UnavailableSupplierAdapter()


def _transport_offer_provider(transport_type: str) -> TransportOfferProvider:
    settings = Settings()
    config = MagicMcpTransportConfig(
        train_url=settings.magic_mcp_train_url,
        train_tool=settings.magic_mcp_train_tool,
        flight_url=settings.magic_mcp_flight_url,
        flight_tool=settings.magic_mcp_flight_tool,
        api_key=settings.magic_mcp_api_key,
        timeout_seconds=settings.magic_mcp_timeout_seconds,
    )
    if transport_type == "train" and config.train_url and config.train_tool and config.api_key and config.timeout_seconds > 0:
        return MagicTrainOfferProvider(config)
    if transport_type == "flight" and config.flight_url and config.flight_tool and config.api_key and config.timeout_seconds > 0:
        return MagicFlightOfferProvider(config)
    return UnavailableTrainOfferProvider() if transport_type == "train" else UnavailableFlightOfferProvider()


def notification_targets(event: Mapping[str, Any]) -> list[str]:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return []
    companion_recipient_fields = {
        "companion_application.created": ("owner_id",),
        "companion_application.accepted": ("applicant_id",),
        "companion_application.rejected": ("applicant_id",),
        "companion_application.withdrawn": ("owner_id",),
        "companion_member.removed": ("user_id",),
        "companion_member.left": ("owner_id",),
        "companion_request.full": ("owner_id",),
        "companion_request.completed": ("owner_id",),
    }
    fields = companion_recipient_fields.get(str(event.get("event_type")), ("user_id", "owner_id", "applicant_id"))
    candidate_ids: list[str] = []
    for key in fields:
        value = payload.get(key)
        if isinstance(value, str):
            candidate_ids.append(value)
    recipient_ids = payload.get("recipient_ids")
    if not companion_recipient_fields.get(str(event.get("event_type"))) and isinstance(recipient_ids, list):
        candidate_ids.extend(value for value in recipient_ids if isinstance(value, str))
    return list(dict.fromkeys(candidate_ids))


def notification_category(event_type: str) -> str:
    if event_type.startswith(("travel_order.", "payment.", "fulfillment.", "refund.")):
        return "order"
    if event_type.startswith(("itinerary.", "route_calculation.", "ai.generation")):
        return "itinerary"
    return "community"


logger = logging.getLogger(__name__)


async def _notification_enabled(session: AsyncSession, user_id: str, category: str) -> bool:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        return True
    return settings.notifications_enabled and bool(getattr(settings, f"{category}_notifications"))


async def _notify_user(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return
    event_type = str(event.get("event_type", "domain.event"))
    category = notification_category(event_type)
    for user_id in notification_targets(event):
        if not await _notification_enabled(session, user_id, category):
            continue
        session.add(
            Notification(
                user_id=user_id,
                notification_type=event_type,
                payload_json=dict(payload),
            )
        )


async def _index_post(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("post_id"), str):
        return
    projection = await session.scalar(
        select(SearchProjection).where(
            SearchProjection.document_type == "post",
            SearchProjection.document_id == payload["post_id"],
        )
    )
    if projection is None:
        projection = SearchProjection(
            document_type="post",
            document_id=payload["post_id"],
            version=1,
        )
        session.add(projection)
    projection.indexed_at = utc_now()
    if event.get("event_type") == "post.hidden":
        projection.unavailable_reason = str(payload.get("reason_code") or "post_hidden")


async def _rebuild_search_index(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("job_id"), str):
        return
    job = await session.scalar(select(SearchIndexRebuildJob).where(SearchIndexRebuildJob.id == payload["job_id"]).with_for_update())
    if job is None or job.status != "queued":
        return
    job.status, job.progress, job.started_at = "running", 5, utc_now()
    if job.index_name == "user_memory":
        job.error = "Rebuild unavailable: user_memory is private and has no administrator-wide source dataset."
    elif job.index_name == "travel_knowledge":
        job.error = "Rebuild unavailable: travel_knowledge has no source-driven adapter in the current implementation."
    elif job.index_name == "community_knowledge":
        if not Settings().ai_enabled:
            job.error = "Rebuild unavailable: AI indexing is not enabled for community_knowledge."
        else:
            posts = list((await session.scalars(select(Post).join(CommunityKnowledgeReview, CommunityKnowledgeReview.post_id == Post.id).where(
                Post.status == "published", Post.city_code.is_not(None), CommunityKnowledgeReview.status == "approved"
            ))).all())
            for position, post in enumerate(posts, start=1):
                await _index_post(session, {"payload": {"post_id": post.id}})
                try:
                    await _index_ai_knowledge(session, {"payload": {"post_id": post.id}})
                except Exception as error:
                    job.error = f"Community knowledge rebuild unavailable while indexing post {post.id}: {error}"[:500]
                    break
                job.progress = 5 + int(position / max(len(posts), 1) * 95)
    elif job.index_name == "official_knowledge":
        sources = list((await session.scalars(select(OfficialKnowledgeSource).where(OfficialKnowledgeSource.status == "indexed", OfficialKnowledgeSource.knowledge_domain == "official"))).all())
        for position, source in enumerate(sources, start=1):
            source.status = "indexing"
            await _index_official_ai_knowledge(session, {"payload": {"knowledge_source_id": source.id}})
            if source.status == "failed":
                job.error = f"Official knowledge source {source.id} failed to index: {source.index_error or 'unknown indexing error'}"[:500]
                break
            job.progress = 5 + int(position / max(len(sources), 1) * 95)
    else:
        job.error = f"Rebuild unavailable: unsupported logical index {job.index_name}."
    job.status = "failed" if job.error else "succeeded"
    job.active_key = None
    job.progress = 100
    job.completed_at = utc_now()


async def _index_ai_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("post_id"), str):
        return
    post = await session.get(Post, payload["post_id"])
    if post is None or post.status != "published" or not post.city_code:
        return
    settings = Settings()
    if not settings.ai_enabled:
        return
    runtime = await open_domain_retrieval_runtime(settings)
    try:
        await runtime.catalog.stores[KnowledgeDomain.COMMUNITY][0].ensure_collection()
        from app.modules.ai_rag.ingestion import KnowledgeIngestionService

        milvus, elasticsearch = runtime.catalog.stores[KnowledgeDomain.COMMUNITY]
        await KnowledgeIngestionService(runtime.embeddings, milvus, elasticsearch).ingest(
            ReviewedKnowledgeDocument(
                document_id=post.id,
                source_type=KnowledgeSourceType.COMMUNITY,
                source_id=post.id,
                text=f"{post.title}\n\n{post.body_text}",
                city_code=post.city_code,
                poi_id=None,
                language="zh-CN",
                visibility="public",
                status="reviewed",
                source_updated_at=post.updated_at,
                knowledge_domain=KnowledgeDomain.COMMUNITY,
                authority_level=AuthorityLevel.COMMUNITY,
            )
        )
    finally:
        await runtime.close()


async def _index_approved_community_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("post_id"), str):
        return
    review = await session.scalar(
        select(CommunityKnowledgeReview).where(
            CommunityKnowledgeReview.post_id == payload["post_id"],
            CommunityKnowledgeReview.status == "approved",
        )
    )
    if review is None:
        return
    await _index_ai_knowledge(session, event)


async def _remove_community_ai_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("post_id"), str):
        return
    settings = Settings()
    if not settings.ai_enabled:
        return
    runtime = await open_domain_retrieval_runtime(settings)
    try:
        milvus, elasticsearch = runtime.catalog.stores[KnowledgeDomain.COMMUNITY]
        await milvus.delete_document(payload["post_id"])
        await elasticsearch.delete_document(payload["post_id"])
    finally:
        await runtime.close()


async def _run_web_knowledge_search(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("job_id"), str):
        return
    job = await session.get(WebKnowledgeSearchJob, payload["job_id"], with_for_update=True)
    if job is None or job.status != "queued":
        return
    settings = Settings()
    if not (settings.magic_mcp_websearch_url and settings.magic_mcp_websearch_tool and settings.magic_mcp_api_key):
        job.status = "failed"
        job.error_code = "WEBSEARCH_UNAVAILABLE"
        job.error_message = "WebSearch MCP is not configured."
        return
    job.status = "running"
    try:
        async with httpx.AsyncClient() as client:
            provider = MagicMcpWebSearchProvider(
                endpoint=settings.magic_mcp_websearch_url,
                tool=settings.magic_mcp_websearch_tool,
                api_key=settings.magic_mcp_api_key,
                timeout=settings.magic_mcp_timeout_seconds,
                client=client,
            )
            results = await provider.search(job.query, limit=20)
    except Exception as error:
        # Roll back the running claim with this delivery so RabbitMQ can retry
        # without prematurely recording the deferred idempotency marker.
        raise DependencyUnavailable("websearch_mcp", "WebSearch MCP is temporarily unavailable.") from error
    eligible_results = tuple(
        item for item in results
        if is_knowledge_candidate_eligible(item, query=job.query, target_domain=job.target_domain)
    )
    for item in eligible_results:
        source_url_hash = sha256(item.source_url.encode("utf-8")).hexdigest()
        exists = await session.scalar(
            select(WebKnowledgeCandidate.id).where(
                WebKnowledgeCandidate.job_id == job.id,
                WebKnowledgeCandidate.source_url_hash == source_url_hash,
            )
        )
        if exists is None:
            session.add(WebKnowledgeCandidate(
                job_id=job.id,
                title=item.title,
                excerpt=item.excerpt,
                source_url=item.source_url,
                source_url_hash=source_url_hash,
                source_host=item.source_host,
                published_at=item.published_at,
                fetched_at=utc_now(),
                excerpt_hash=sha256(item.excerpt.encode("utf-8")).hexdigest(),
                city_code=job.city_code,
                target_domain=job.target_domain,
            ))
    job.status = "succeeded"
    job.provider_name = "magic_mcp"
    job.error_code = None
    job.error_message = None
    job.result_count = len(eligible_results)


async def _finalize_web_knowledge_search_failure(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("job_id"), str):
        return
    job = await session.get(WebKnowledgeSearchJob, payload["job_id"], with_for_update=True)
    if job is None or job.status not in {"queued", "running"}:
        return
    job.status = "failed"
    job.error_code = "WEBSEARCH_UNAVAILABLE"
    job.error_message = "WebSearch MCP was unavailable after retrying. Submit a new search when the service recovers."


async def _index_official_ai_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("knowledge_source_id"), str):
        return
    source = await session.get(OfficialKnowledgeSource, payload["knowledge_source_id"])
    if source is None or source.status != "indexing":
        return
    settings = Settings()
    if not settings.ai_enabled:
        source.status = "failed"
        source.index_error = "AI indexing is not enabled for this environment."
        return
    try:
        validate_source_version(
            source.source_version,
            document_id=source.id,
            supersedes_document_id=source.supersedes_document_id,
        )
    except ValueError as error:
        source.status = "failed"
        source.index_error = str(error)[:500]
        return
    runtime = await open_domain_retrieval_runtime(settings)
    try:
        from app.modules.ai_rag.ingestion import KnowledgeIngestionService

        milvus, elasticsearch = runtime.catalog.stores[KnowledgeDomain.OFFICIAL]
        await KnowledgeIngestionService(runtime.embeddings, milvus, elasticsearch).ingest(
            ReviewedKnowledgeDocument(
                document_id=source.id,
                source_type=KnowledgeSourceType(source.source_type),
                source_id=source.id,
                text=f"{source.title}\n\n{source.body_text}",
                city_code=source.city_code,
                poi_id=source.poi_id,
                language=source.language,
                visibility="public",
                status="reviewed",
                source_updated_at=source.updated_at,
                knowledge_domain=KnowledgeDomain(source.knowledge_domain),
                authority_level=AuthorityLevel.OFFICIAL,
                reviewed_at=_utc_or_none(source.reviewed_at),
                next_review_at=_utc_or_none(source.next_review_at),
                source_version=source.source_version,
                supersedes_document_id=source.supersedes_document_id,
            )
        )
        source.status = "indexed"
        source.indexed_at = utc_now()
        source.index_error = None
    except Exception as error:
        source.status = "failed"
        source.index_error = str(error)[:500]
    finally:
        await runtime.close()


async def _index_external_web_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("source_id"), str):
        return
    source = await session.get(ExternalWebKnowledgeSource, payload["source_id"])
    if source is None or source.status != "indexing":
        return
    settings = Settings()
    if not settings.ai_enabled:
        source.status = "failed"
        source.index_error = "AI indexing is not enabled for this environment."
        return
    domain = KnowledgeDomain.OFFICIAL if source.target_domain == "official" else KnowledgeDomain.COMMUNITY
    runtime = await open_domain_retrieval_runtime(settings)
    try:
        from app.modules.ai_rag.ingestion import KnowledgeIngestionService

        milvus, elasticsearch = runtime.catalog.stores[domain]
        await KnowledgeIngestionService(runtime.embeddings, milvus, elasticsearch).ingest(
            ReviewedKnowledgeDocument(
                document_id=source.id,
                source_type=KnowledgeSourceType.RULE if domain is KnowledgeDomain.OFFICIAL else KnowledgeSourceType.COMMUNITY,
                source_id=source.id,
                text=f"{source.title}\n\n{source.body_text}",
                city_code=source.city_code,
                poi_id=None,
                language="zh-CN",
                visibility="public",
                status="reviewed",
                source_updated_at=source.updated_at,
                knowledge_domain=domain,
                authority_level=AuthorityLevel.OFFICIAL if domain is KnowledgeDomain.OFFICIAL else AuthorityLevel.COMMUNITY,
                reviewed_at=source.reviewed_at,
            )
        )
        source.status = "indexed"
        source.indexed_at = utc_now()
        source.index_error = None
    except Exception as error:
        source.status = "failed"
        source.index_error = str(error)[:500]
    finally:
        await runtime.close()


async def _remove_official_ai_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("knowledge_source_id"), str):
        return
    source = await session.get(OfficialKnowledgeSource, payload["knowledge_source_id"])
    if source is None or source.status != "removing":
        return
    settings = Settings()
    if not settings.ai_enabled:
        source.status = "indexed"
        source.removal_error = "AI indexing is not enabled for this environment."
        return
    runtime = await open_domain_retrieval_runtime(settings)
    try:
        milvus, elasticsearch = runtime.catalog.stores[KnowledgeDomain.OFFICIAL]
        await milvus.delete_document(source.id)
        await elasticsearch.delete_document(source.id)
        source.status = "inactive"
        source.removal_error = None
    except Exception as error:
        # Keep MySQL aligned with its still-present public projections for retry.
        source.status = "indexed"
        source.removal_error = str(error)[:500]
    finally:
        await runtime.close()


async def _import_poi_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("poi_knowledge_import_job_id"), str):
        return
    job = await session.get(PoiKnowledgeImportJob, payload["poi_knowledge_import_job_id"])
    if job is None or job.status != "queued":
        return
    job.status = "running"
    try:
        service = AMapService()
        seen_poi_ids: set[str] = set()
        for keyword in job.keywords:
            matches = await service.search_pois(keyword, job.city_code)
            poi = next((item for item in matches if item.adcode and _city_code_matches(job.city_code, item.adcode)), None)
            if poi is None or poi.id in seen_poi_ids:
                job.skipped_count += 1
                continue
            seen_poi_ids.add(poi.id)
            existing = await session.scalar(select(OfficialKnowledgeSource).where(OfficialKnowledgeSource.poi_id == poi.id))
            if existing is not None:
                if existing.status == "indexing":
                    # Recover a source created before a prior batch delivery failed.
                    session.add(OutboxEvent(
                        event_type="ai.official_knowledge_index_requested",
                        aggregate_type="official_knowledge_source",
                        aggregate_id=existing.id,
                        trace_id=new_uuid(),
                        payload_json={"knowledge_source_id": existing.id},
                    ))
                    job.imported_count += 1
                    continue
                job.skipped_count += 1
                continue
            source = OfficialKnowledgeSource(
                source_type="poi",
                title=poi.name,
                body_text=(
                    f"Verified AMap POI: {poi.name}. Address: {poi.address}. "
                    f"POI ID: {poi.id}. Use it only after AMap verification during itinerary confirmation."
                ),
                city_code=job.city_code,
                poi_id=poi.id,
                language="zh-CN",
                status="indexing",
                source_version="1",
                review_reason="Batch imported from AMap using an administrator-approved keyword.",
                reviewed_by=job.requested_by,
                reviewed_at=utc_now(),
            )
            validate_source_version(source.source_version, document_id=source.id, supersedes_document_id=source.supersedes_document_id)
            source.next_review_at = derive_next_review_at(source.source_type, source.reviewed_at)
            session.add(source)
            await session.flush()
            session.add(OutboxEvent(
                event_type="ai.official_knowledge_index_requested",
                aggregate_type="official_knowledge_source",
                aggregate_id=source.id,
                trace_id=new_uuid(),
                payload_json={"knowledge_source_id": source.id},
            ))
            job.imported_count += 1
        job.status = "succeeded"
        job.error_message = None
    except Exception as error:
        job.status = "failed"
        job.error_message = str(error)[:500]


async def _record_confirmed_preview_poi_candidates(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("generation_job_id"), str):
        return
    poi_ids = payload.get("poi_ids")
    if not isinstance(poi_ids, list):
        return
    job = await session.get(GenerationJob, payload["generation_job_id"])
    if job is None:
        return
    maps = AMapService()
    for poi_id in dict.fromkeys(item for item in poi_ids if isinstance(item, str) and item):
        poi = await maps.verify_poi(poi_id)
        if isinstance(poi, MapUnavailable) or poi.adcode is None:
            continue
        if not _city_code_matches(job.city_code, poi.adcode) or not _is_attraction_type(poi.type_name):
            continue
        candidate = await session.scalar(select(PoiCandidate).where(PoiCandidate.poi_id == poi.id))
        if candidate is None:
            session.add(PoiCandidate(
                poi_id=poi.id,
                name=poi.name,
                address=poi.address,
                city_code=_normalized_city_code(poi.adcode),
                longitude=poi.location[0],
                latitude=poi.location[1],
                amap_type=poi.type_name,
            ))
            continue
        candidate.name = poi.name
        candidate.address = poi.address
        candidate.city_code = _normalized_city_code(poi.adcode)
        candidate.longitude, candidate.latitude = poi.location
        candidate.amap_type = poi.type_name
        candidate.discovery_count += 1
        candidate.confirmed_itinerary_count += 1


async def _import_structured_knowledge(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("structured_knowledge_import_job_id"), str):
        return
    job = await session.get(StructuredKnowledgeImportJob, payload["structured_knowledge_import_job_id"])
    if job is None or job.status != "queued":
        return
    job.status = "running"
    try:
        for entry in job.entries:
            source_type = entry.get("source_type")
            title = entry.get("title")
            body_text = entry.get("body_text")
            if source_type not in {"rule", "template"} or not isinstance(title, str) or not isinstance(body_text, str):
                raise ValueError("Structured knowledge entries must contain a rule or template title and body.")
            existing = await session.scalar(select(OfficialKnowledgeSource).where(
                OfficialKnowledgeSource.source_type == source_type,
                OfficialKnowledgeSource.city_code == job.city_code,
                OfficialKnowledgeSource.title == title,
                OfficialKnowledgeSource.body_text == body_text,
            ))
            if existing is not None:
                if existing.status == "indexing":
                    session.add(OutboxEvent(
                        event_type="ai.official_knowledge_index_requested",
                        aggregate_type="official_knowledge_source",
                        aggregate_id=existing.id,
                        trace_id=new_uuid(),
                        payload_json={"knowledge_source_id": existing.id},
                    ))
                    job.imported_count += 1
                else:
                    job.skipped_count += 1
                continue
            source = OfficialKnowledgeSource(
                source_type=source_type,
                title=title,
                body_text=body_text,
                city_code=job.city_code,
                language="zh-CN",
                status="indexing",
                source_version="1",
                review_reason="Batch imported from administrator-reviewed structured knowledge.",
                reviewed_by=job.requested_by,
                reviewed_at=utc_now(),
            )
            validate_source_version(source.source_version, document_id=source.id, supersedes_document_id=source.supersedes_document_id)
            source.next_review_at = derive_next_review_at(source.source_type, source.reviewed_at)
            session.add(source)
            await session.flush()
            session.add(OutboxEvent(
                event_type="ai.official_knowledge_index_requested",
                aggregate_type="official_knowledge_source",
                aggregate_id=source.id,
                trace_id=new_uuid(),
                payload_json={"knowledge_source_id": source.id},
            ))
            job.imported_count += 1
        job.status = "succeeded"
        job.error_message = None
    except Exception as error:
        job.status = "failed"
        job.error_message = str(error)[:500]


def _city_code_matches(requested_city_code: str, poi_adcode: str) -> bool:
    if requested_city_code == poi_adcode:
        return True
    if len(requested_city_code) != 6 or len(poi_adcode) != 6 or not requested_city_code.endswith("00"):
        return False
    if requested_city_code[:4] == poi_adcode[:4]:
        return True
    # Municipalities use a province-level city code (for example, 110000)
    # while AMap returns district adcodes such as 110105.
    return requested_city_code[:2] in {"11", "12", "31", "50"} and requested_city_code[:2] == poi_adcode[:2]


def _is_attraction_type(type_name: str | None) -> bool:
    return isinstance(type_name, str) and any(
        hint in type_name
        for hint in ("风景名胜", "公园", "博物馆", "纪念馆", "展览馆", "动物园", "植物园", "海滨", "海岛")
    )


def _normalized_city_code(adcode: str) -> str:
    return f"{adcode[:4]}00" if len(adcode) == 6 else adcode


def _utc_or_none(value: object):
    from datetime import UTC

    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _record_projection(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return
    aggregate_id = event.get("aggregate_id")
    aggregate_type = event.get("aggregate_type")
    if not isinstance(aggregate_id, str) or not isinstance(aggregate_type, str):
        return
    projection = await session.scalar(
        select(SearchProjection).where(
            SearchProjection.document_type == aggregate_type,
            SearchProjection.document_id == aggregate_id,
        )
    )
    if projection is None:
        session.add(SearchProjection(document_type=aggregate_type, document_id=aggregate_id, version=1))
    else:
        projection.indexed_at = utc_now()


async def _calculate_route(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("route_calculation_job_id"), str):
        return
    await ItineraryService(session).process_route_calculation(payload["route_calculation_job_id"])


async def _run_generation(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("generation_job_id"), str):
        return
    service = GenerationJobService(session)
    job = await service.start_attempt(
        payload["generation_job_id"],
        trace_id=str(event.get("trace_id") or "") or None,
    )
    if job is None:
        return
    # Persist the claim before calling external providers so each delivery is audited.
    await session.commit()
    runtime = None
    try:
        settings = Settings()
        if not settings.ai_enabled:
            await service.mark_unavailable(job.id, "AI planning is not enabled for this environment.")
            return
        runtime = await open_ai_runtime(settings)
        base_snapshot = job.request_json.get("base_snapshot")
        is_targeted_modification = isinstance(base_snapshot, Mapping)
        request = GenerationRequest(
            generation_job_id=job.id,
            user_id=job.user_id,
            prompt=_live_search_query(job),
            city_code=job.city_code,
            start_date=job.start_date,
            end_date=job.end_date,
            budget_amount=job.request_json.get("budget_amount"),
            currency=str(job.request_json.get("currency") or "CNY"),
            target_itinerary_id=job.target_itinerary_id if is_targeted_modification else None,
            base_version=job.request_json.get("base_version") if is_targeted_modification else None,
            base_snapshot=base_snapshot if is_targeted_modification else None,
            preference_tags=tuple(
                tag for tag in job.request_json.get("preference_tags", ()) if isinstance(tag, str)
            ),
        )
        trace_id = job.trace_id
        if trace_id is None:
            raise DependencyUnavailable("generation_job", "Generation attempt is unavailable.")
        progress_by_status = {
            "retrieving": 20,
            "retrieving_reviewed_sources": 30,
            "searching_live_sources": 45,
            "verifying_pois": 60,
            "planning": 75,
            "validating": 90,
        }

        async def mark_workflow_progress(status: str) -> None:
            progress = progress_by_status.get(status)
            if progress is None:
                return
            await service.mark_progress(job.id, status=status, progress=progress, trace_id=trace_id)
            # Publish each durable phase transition to API pollers before the
            # workflow moves on to slower external calls.
            await session.commit()

        request = GenerationRequest(
            generation_job_id=request.generation_job_id,
            user_id=request.user_id,
            prompt=request.prompt,
            city_code=request.city_code,
            start_date=request.start_date,
            end_date=request.end_date,
            budget_amount=request.budget_amount,
            currency=request.currency,
            target_itinerary_id=request.target_itinerary_id,
            base_version=request.base_version,
            base_snapshot=request.base_snapshot,
            progress_callback=mark_workflow_progress,
            workflow_run_id=trace_id,
            preference_tags=request.preference_tags,
            must_visit_poi_ids=tuple(
                poi_id
                for poi_id in job.request_json.get("must_visit_poi_ids", ())
                if isinstance(poi_id, str) and poi_id
            ),
        )
        workflow = runtime.workflow_factory.create(runtime.dependencies())
        state = await workflow.run(request)
        if state.preview is None:
            await service.mark_no_result(
                job.id, "PREVIEW_NOT_CREATED", "AI planning did not create a confirmation preview."
            )
            return
        await service.mark_preview_ready(job.id, state.preview.preview_id)
    except InsufficientVerifiedCandidates as error:
        await service.mark_no_result(job.id, error.code, error.message)
    except ConstraintViolation as error:
        await service.mark_no_result(job.id, error.code, str(error))
    except RequestValidationError as error:
        await service.mark_no_result(job.id, error.code, str(error))
    except DraftSchemaError as error:
        await service.mark_invalid_draft(job.id, f"The model returned an invalid itinerary draft: {error}")
    except DependencyUnavailable as error:
        logger.exception(
            "Generation job %s failed due to unavailable dependency: source=%s message=%s",
            job.id, error.dependency, str(error),
        )
        await _prepare_generation_retry(session, job.id, source=error.dependency, detail=str(error))
        raise
    except Exception as error:
        logger.exception("Generation job %s failed with unexpected error: %s", job.id, error)
        await _prepare_generation_retry(session, job.id, source="unexpected", detail=str(error))
        raise
    finally:
        if runtime is not None:
            try:
                await runtime.close()
            except Exception:
                pass


def _live_search_query(job: GenerationJob) -> str:
    """Build bounded live-search input from the immutable public request snapshot."""
    destination = job.request_json.get("destination")
    destination_name = destination.get("name") if isinstance(destination, Mapping) else None
    parts = [destination_name.strip()] if isinstance(destination_name, str) and destination_name.strip() else []
    preference_tags = job.request_json.get("preference_tags")
    if isinstance(preference_tags, list):
        parts.extend(tag.strip() for tag in preference_tags[:3] if isinstance(tag, str) and tag.strip())
    prompt = job.request_json.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        parts.append(prompt.strip())
    if "经典必玩" in preference_tags if isinstance(preference_tags, list) else False:
        parts.extend(("旅游景点", "必去"))
    return " ".join(parts)[:500]


async def _prepare_generation_retry(
    session: AsyncSession,
    job_id: str,
    *,
    source: str = "unknown",
    detail: str = "",
) -> None:
    """Release a claimed job while retaining its persisted attempt metadata."""
    job = await session.get(GenerationJob, job_id)
    if job is None:
        return
    job.status = "queued"
    job.progress = 0
    job.last_error_code = f"DEPENDENCY_UNAVAILABLE:{source}"
    summary = f"Dependency unavailable ({source})"
    if detail:
        summary += f": {detail[:400]}"
    job.last_error_message = summary
    await session.commit()


async def _finalize_generation_failure(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("generation_job_id"), str):
        return
    job = await session.get(GenerationJob, payload["generation_job_id"])
    if job is None or job.status != "queued":
        return
    # The failed delivery already recorded its attempt; activate it only long
    # enough for the service's terminal-state guard to apply.
    recorded_code = job.last_error_code
    recorded_message = job.last_error_message
    job.status = "understanding"
    job.progress = 10
    await GenerationJobService(session).mark_unavailable(
        job.id, "AI planning dependencies are temporarily unavailable."
    )
    # Keep the specific dependency source recorded by the failed attempt
    # (e.g. DEPENDENCY_UNAVAILABLE:websearch_mcp) instead of the generic code,
    # so operators can see what actually broke.
    if recorded_code:
        job.error_code = job.last_error_code = recorded_code
        if recorded_message:
            job.message = job.last_error_message = recorded_message


async def _cleanup_expired_media_uploads(session: AsyncSession, _event: Mapping[str, Any]) -> None:
    try:
        settings = Settings()
        storage = S3ObjectStorage(settings)
    except StorageUnavailable:
        storage = None
    await expire_pending_uploads(session, storage)


async def _run_export(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("export_task_id"), str):
        return
    service = ExportTaskService(session)
    task = await service.start_attempt(payload["export_task_id"], trace_id=str(event.get("trace_id") or "") or None)
    if task is None:
        return
    # Claim is durable before object storage work so re-delivery records a new attempt.
    await session.commit()
    try:
        document = render_docx(task.snapshot_json)
        storage = S3ObjectStorage(Settings(), bucket=Settings().s3_bucket_exports)
        await service.complete(task.id, document, storage)
    except StorageUnavailable:
        await service.prepare_retry(task.id)
        raise
    except Exception:
        await service.prepare_retry(task.id)
        raise


async def _fulfill_paid_order(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("payment_id"), str):
        return
    from app.modules.orders.models import PaymentRecord

    payment = await session.get(PaymentRecord, payload["payment_id"])
    if payment is None:
        return
    ticket = await session.scalar(
        select(MockTransportTicket).where(MockTransportTicket.order_id == payment.order_id)
    )
    if ticket is not None:
        await MockTicketService(
            session,
            DeterministicMockTransportTicketIssuer(),
            _transport_offer_provider(ticket.transport_type),
        ).issue_paid_ticket(payment.id)
        return
    service = FulfillmentService(session, fulfillment_supplier)
    attempt = await service.start_attempt(payload["payment_id"])
    if attempt is None:
        return
    # Commit the claim before the supplier call so a duplicate delivery cannot book twice.
    await session.commit()
    try:
        await service.confirm(attempt)
    except SupplierFulfillmentUnavailable:
        await service.prepare_retry(attempt.travel_order_id)
        raise


async def _process_refund(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("refund_id"), str):
        return
    await RefundService(session, get_alipay_adapter(Settings())).process(payload["refund_id"])


async def _finalize_export_failure(session: AsyncSession, event: Mapping[str, Any]) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping) or not isinstance(payload.get("export_task_id"), str):
        return
    await ExportTaskService(session).finalize_failure(payload["export_task_id"])


async def _cleanup_expired_exports(session: AsyncSession, _event: Mapping[str, Any]) -> None:
    try:
        settings = Settings()
        storage = S3ObjectStorage(settings, bucket=settings.s3_bucket_exports)
    except StorageUnavailable:
        storage = None
    await expire_succeeded_exports(session, storage)


def register_domain_handlers() -> None:
    routes = registered_routes.snapshot()
    registrations = (
        ("admin.search_index_rebuild_requested", "admin.search_index.rebuild", _rebuild_search_index),
        ("post.published", "search.post.index", _index_post),
        ("ai.official_knowledge_index_requested", "ai.official_knowledge.index", _index_official_ai_knowledge),
        ("ai.external_web_knowledge_index_requested", "ai.external_web_knowledge.index", _index_external_web_knowledge),
        ("ai.community_knowledge_index_requested", "ai.community_knowledge.index", _index_approved_community_knowledge),
        ("ai.official_knowledge_removal_requested", "ai.official_knowledge.remove", _remove_official_ai_knowledge),
        ("ai.poi_knowledge_import_requested", "ai.poi_knowledge.import", _import_poi_knowledge),
        ("ai.confirmed_preview_poi_discovery_requested", "ai.poi_candidate.discovery", _record_confirmed_preview_poi_candidates),
        ("ai.structured_knowledge_import_requested", "ai.structured_knowledge.import", _import_structured_knowledge),
        (
            "ai.web_knowledge_search_requested",
            "ai.web_knowledge.search",
            _run_web_knowledge_search,
            True,
            _finalize_web_knowledge_search_failure,
        ),
        ("post.hidden", "search.post.remove", _index_post),
        ("post.hidden", "ai.community_knowledge.remove", _remove_community_ai_knowledge),
        ("companion_application.created", "notifications.companion", _notify_user),
        ("companion_application.accepted", "notifications.companion", _notify_user),
        ("companion_application.rejected", "notifications.companion", _notify_user),
        ("companion_application.withdrawn", "notifications.companion", _notify_user),
        ("companion_member.removed", "notifications.companion", _notify_user),
        ("companion_member.left", "notifications.companion", _notify_user),
        ("companion_request.full", "notifications.companion", _notify_user),
        ("companion_request.completed", "notifications.companion", _notify_user),
        ("message.created", "notifications.message", _notify_user),
        ("travel_search_job.completed", "notifications.search", _notify_user),
        ("travel_order.created", "notifications.order", _notify_user),
        ("travel_order.fulfillment_updated", "notifications.fulfillment", _notify_user),
        ("payment_record.paid", "orders.payment", _record_projection),
        ("payment_record.paid", "orders.fulfillment", _fulfill_paid_order, True),
        ("refund_record.requested", "orders.refund.process", _process_refund, True),
        ("refund_record.updated", "orders.refund", _record_projection),
        ("itinerary.route_calculation_requested", "itineraries.route_calculation", _calculate_route),
        (MEDIA_UPLOAD_CLEANUP_EVENT, "media.expired_upload_cleanup", _cleanup_expired_media_uploads),
        (
            "ai.generation_requested",
            "ai.generation",
            _run_generation,
            True,
            _finalize_generation_failure,
        ),
        (
            EXPORT_REQUESTED_EVENT,
            "exports.docx",
            _run_export,
            True,
            _finalize_export_failure,
        ),
        (EXPORT_EXPIRATION_CLEANUP_EVENT, "exports.expiration_cleanup", _cleanup_expired_exports),
        (EXPORT_COMPLETED_EVENT, "notifications.export", _notify_user),
    )
    for registration in registrations:
        event_type, consumer_name, handler, *options = registration
        if not any(route.consumer_name == consumer_name for route in routes.get(event_type, ())):
            registered_routes.register(
                event_type,
                consumer_name,
                handler,
                defer_idempotency=bool(options[0]) if options else False,
                terminal_failure_handler=options[1] if len(options) > 1 else None,
            )
