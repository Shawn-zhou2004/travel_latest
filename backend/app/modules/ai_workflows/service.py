from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.modules.ai_entitlements.service import AIEntitlementError, AIEntitlementService
from app.modules.ai_workflows.models import GenerationJob
from app.modules.ai_workflows.schemas import GenerationJobCreate, GenerationJobStatus
from app.modules.itineraries.models import Itinerary, ItineraryVersion


class GenerationJobError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409, details: dict[str, object] | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class GenerationJobService:
    _ACTIVE_STATUSES = {
        "queued",
        "understanding",
        "resolving_destination",
        "retrieving",
        "retrieving_reviewed_sources",
        "searching_live_sources",
        "verifying_pois",
        "planning",
        "validating",
    }
    _PROGRESS_STAGE_ORDER = {
        "understanding": 0,
        "resolving_destination": 1,
        "retrieving": 2,
        "retrieving_reviewed_sources": 3,
        "searching_live_sources": 4,
        "verifying_pois": 5,
        "planning": 6,
        "validating": 7,
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: str, idempotency_key: str, body: GenerationJobCreate) -> GenerationJob:
        target_itinerary_id = body.target_itinerary_id
        city_code = body.destination.city_code if body.destination is not None else None
        target_snapshot: dict | None = None
        if target_itinerary_id is not None:
            itinerary = await self.session.get(Itinerary, target_itinerary_id)
            if itinerary is None or itinerary.owner_id != user_id:
                raise GenerationJobError("TARGET_ITINERARY_NOT_FOUND", "The target itinerary is unavailable.", 404)
            if body.start_date != itinerary.start_date or body.end_date != itinerary.end_date:
                raise GenerationJobError("TARGET_DATE_RANGE_MISMATCH", "Targeted generation must use the itinerary date range.", 422)
            if body.base_version != itinerary.version:
                raise GenerationJobError("TARGET_VERSION_CONFLICT", "base_version must match the current itinerary version.")
            snapshot_version = await self.session.scalar(select(ItineraryVersion).where(
                ItineraryVersion.itinerary_id == itinerary.id,
                ItineraryVersion.version == body.base_version,
            ))
            if snapshot_version is None or not any(
                isinstance(day, dict) and day.get("events")
                for day in snapshot_version.snapshot.get("days", [])
            ):
                raise GenerationJobError("TARGET_ITINERARY_EMPTY", "The target itinerary must contain at least one activity.", 422)
            target_snapshot = snapshot_version.snapshot
            if city_code is None:
                city_code = await self.session.scalar(
                    select(GenerationJob.city_code)
                    .where(GenerationJob.target_itinerary_id == itinerary.id)
                    .order_by(GenerationJob.created_at.desc())
                    .limit(1)
                )
                if city_code is None:
                    raise GenerationJobError("TARGET_DESTINATION_UNAVAILABLE", "The target itinerary has no known destination.", 422)
        if city_code is None:
            raise GenerationJobError("DESTINATION_REQUIRED", "A destination is required for a new itinerary.", 422)
        request_json = self._request_snapshot(body, city_code)
        if target_snapshot is not None:
            request_json["base_snapshot"] = target_snapshot
        existing = await self.session.scalar(
            select(GenerationJob).where(
                GenerationJob.user_id == user_id,
                GenerationJob.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            existing_request = dict(existing.request_json)
            existing_request.pop("base_snapshot", None)
            if existing_request != request_json:
                raise GenerationJobError("IDEMPOTENCY_CONFLICT", "Idempotency-Key is already bound to another generation request.")
            return existing
        try:
            await AIEntitlementService(self.session).consume(user_id, "itinerary_generation")
        except AIEntitlementError as error:
            raise GenerationJobError(error.code, error.message, error.status_code, {
                "remaining": 0,
                "period_end": error.period_end.isoformat(),
                "upgrade_available": error.upgrade_available,
            }) from error
        if target_itinerary_id is None:
            itinerary = Itinerary(
                owner_id=user_id,
                title="AI itinerary preview",
                start_date=body.start_date,
                end_date=body.end_date,
            )
            self.session.add(itinerary)
            await self.session.flush()
            self.session.add(ItineraryVersion(
                itinerary_id=itinerary.id,
                version=itinerary.version,
                snapshot={
                    "title": itinerary.title,
                    "start_date": itinerary.start_date.isoformat(),
                    "end_date": itinerary.end_date.isoformat(),
                    "days": [],
                },
                created_by=user_id,
            ))
            target_itinerary_id = itinerary.id
        job = GenerationJob(
            user_id=user_id,
            target_itinerary_id=target_itinerary_id,
            idempotency_key=idempotency_key,
            city_code=city_code,
            prompt=body.prompt,
            start_date=body.start_date,
            end_date=body.end_date,
            request_json=request_json,
        )
        self.session.add(job)
        await self.session.flush()
        self._enqueue(job)
        await self.session.commit()
        return job

    async def get(self, job_id: str, user_id: str, *, is_admin: bool = False) -> GenerationJob | None:
        job = await self.session.get(GenerationJob, job_id)
        if job is None or (not is_admin and job.user_id != user_id):
            return None
        return job

    async def retry(self, job_id: str, user_id: str, *, is_admin: bool = False) -> GenerationJob | None:
        job = await self.get(job_id, user_id, is_admin=is_admin)
        if job is None:
            return None
        if job.status not in {"failed", "cancelled"}:
            raise GenerationJobError("GENERATION_RETRY_NOT_ALLOWED", "Only failed or cancelled jobs can be retried.")
        job.status = "queued"
        job.progress = 0
        job.outcome = None
        job.error_code = None
        job.message = None
        job.preview_id = None
        job.finished_at = None
        self._enqueue(job)
        await self.session.commit()
        return job

    async def list_pending(self, user_id: str, *, is_admin: bool = False, limit: int = 30) -> list[GenerationJob]:
        """List jobs whose immutable AI preview is waiting for user confirmation."""
        stmt = select(GenerationJob).where(
            GenerationJob.status == "awaiting_confirmation",
            GenerationJob.preview_id.is_not(None),
        )
        if not is_admin:
            stmt = stmt.where(GenerationJob.user_id == user_id)
        stmt = stmt.order_by(GenerationJob.created_at.desc()).limit(limit)
        return list(await self.session.scalars(stmt))

    async def start_attempt(self, job_id: str, trace_id: str | None = None) -> GenerationJob | None:
        """Record one worker execution in the current transaction.

        The caller must commit this transaction before external work begins.
        Re-delivery of an already-running or terminal job returns ``None`` so
        only the caller that claims ``queued`` may execute the work.
        """

        job = await self.session.scalar(
            select(GenerationJob).where(GenerationJob.id == job_id).with_for_update()
        )
        if job is None:
            return None
        if job.status != "queued":
            return None
        job.attempt_count += 1
        job.last_attempt_at = utc_now()
        job.trace_id = trace_id or job.trace_id or new_uuid()
        job.status = "understanding"
        job.progress = 10
        job.outcome = None
        job.last_error_code = None
        job.last_error_message = None
        job.error_code = None
        job.message = None
        job.finished_at = None
        await self.session.flush()
        return job

    async def mark_progress(
        self,
        job_id: str,
        *,
        status: GenerationJobStatus,
        progress: int,
        trace_id: str,
    ) -> GenerationJob | None:
        """Advance a claimed worker attempt without replacing terminal job data."""
        if status not in self._PROGRESS_STAGE_ORDER or not 0 <= progress <= 99:
            return None
        job = await self.session.scalar(
            select(GenerationJob).where(GenerationJob.id == job_id).with_for_update()
        )
        if (
            job is None
            or job.status not in self._ACTIVE_STATUSES
            or job.trace_id != trace_id
            or job.status == "queued"
        ):
            return None
        current_stage = self._PROGRESS_STAGE_ORDER.get(job.status)
        next_stage = self._PROGRESS_STAGE_ORDER[status]
        if current_stage is None or next_stage < current_stage or progress < job.progress:
            return None
        job.status = status
        job.progress = progress
        await self.session.flush()
        return job

    async def mark_unavailable(self, job_id: str, message: str) -> None:
        job = await self.session.get(GenerationJob, job_id)
        if job is None or job.status not in self._ACTIVE_STATUSES:
            return
        job.status = "failed"
        job.progress = 100
        job.outcome = "unavailable"
        job.error_code = "AI_DEPENDENCY_UNAVAILABLE"
        job.message = self._safe_error_message(message)
        self._mark_finished(job, job.error_code, job.message)

    async def mark_invalid_draft(self, job_id: str, message: str) -> None:
        job = await self.session.get(GenerationJob, job_id)
        if job is None or job.status not in self._ACTIVE_STATUSES:
            return
        job.status = "failed"
        job.progress = 100
        job.outcome = "unavailable"
        job.error_code = "INVALID_DRAFT_SCHEMA"
        job.message = self._safe_error_message(message)
        self._mark_finished(job, job.error_code, job.message)

    async def mark_no_result(self, job_id: str, code: str, message: str) -> None:
        job = await self.session.get(GenerationJob, job_id)
        if job is None or job.status not in self._ACTIVE_STATUSES:
            return
        job.status = "succeeded"
        job.progress = 100
        job.outcome = "no_result"
        job.error_code = self._safe_error_code(code)
        job.message = self._safe_error_message(message)
        self._mark_finished(job, job.error_code, job.message)

    async def mark_preview_ready(self, job_id: str, preview_id: str) -> None:
        job = await self.session.get(GenerationJob, job_id)
        if job is None or job.status not in self._ACTIVE_STATUSES:
            return
        job.status = "awaiting_confirmation"
        job.progress = 100
        job.outcome = "preview"
        job.preview_id = preview_id
        job.error_code = None
        job.message = "A source-backed itinerary preview is ready for confirmation."
        self._mark_finished(job)

    @staticmethod
    def _mark_finished(
        job: GenerationJob,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        job.last_error_code = GenerationJobService._safe_error_code(error_code) if error_code else None
        job.last_error_message = GenerationJobService._safe_error_message(error_message) if error_message else None
        job.finished_at = utc_now()

    @staticmethod
    def _safe_error_code(code: str) -> str:
        return str(code).strip()[:64] or "GENERATION_FAILED"

    @staticmethod
    def _safe_error_message(message: str) -> str:
        return " ".join(str(message).split())[:500]

    def _enqueue(self, job: GenerationJob) -> None:
        trace_id = new_uuid()
        job.trace_id = trace_id
        self.session.add(
            OutboxEvent(
                event_type="ai.generation_requested",
                aggregate_type="generation_job",
                aggregate_id=job.id,
                trace_id=trace_id,
                payload_json={"generation_job_id": job.id, "user_id": job.user_id},
            )
        )

    @staticmethod
    def _request_snapshot(body: GenerationJobCreate, city_code: str) -> dict[str, object]:
        snapshot = body.model_dump(mode="json", exclude_none=False)
        snapshot["preference_tags"] = snapshot["preference_tags"] or []
        snapshot["pace"] = snapshot["pace"] or "balanced"
        snapshot["city_code"] = city_code
        return snapshot
