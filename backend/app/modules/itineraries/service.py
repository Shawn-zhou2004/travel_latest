from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.ai_workflows.models import GenerationJob
from app.modules.community.models import CompanionRequest, Post
from app.modules.exports.models import ExportTask
from app.modules.itineraries.models import Itinerary, ItineraryCopyOperation, ItineraryDay, ItineraryEvent, ItineraryVersion, RouteCalculationJob, RouteSegment, TripCollaborator, TripOperation, TripShareToken
from app.modules.maps.service import AMapService, MapUnavailable


@dataclass(frozen=True)
class OperationResult:
    code: str
    current_version: int | None = None
    snapshot: dict[str, Any] | None = None
    idempotent: bool = False
    route_job: RouteCalculationJob | None = None


@dataclass(frozen=True)
class FieldNoteCopyResult:
    itinerary: Itinerary
    idempotent: bool


class ItineraryCopyError(Exception):
    pass


class ItineraryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ItineraryService:
    def __init__(self, session: AsyncSession, map_service: AMapService | None = None) -> None:
        self.session = session
        self.map_service = map_service or AMapService()

    async def create_itinerary(self, owner_id: str, *, title: str, start_date: date, end_date: date) -> Itinerary:
        duration = (end_date - start_date).days + 1
        if not 1 <= duration <= 7:
            raise ValueError("An itinerary must span one to seven days.")
        itinerary = Itinerary(owner_id=owner_id, title=title, start_date=start_date, end_date=end_date)
        self.session.add(itinerary)
        await self.session.flush()
        await self._record_version(itinerary, owner_id)
        await self.session.commit()
        return itinerary

    async def copy_field_note(self, post: Any, actor_id: str, idempotency_key: str) -> FieldNoteCopyResult:
        existing = await self.session.scalar(select(ItineraryCopyOperation).where(
            ItineraryCopyOperation.actor_id == actor_id,
            ItineraryCopyOperation.source_post_id == post.id,
            ItineraryCopyOperation.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            itinerary = await self.session.get(Itinerary, existing.itinerary_id)
            if itinerary is None:
                raise ItineraryCopyError("The original copy is unavailable.")
            return FieldNoteCopyResult(itinerary, True)

        snapshot = _validate_public_field_note_snapshot(post.itinerary_snapshot_json)
        try:
            start_date = date.fromisoformat(snapshot["start_date"])
            end_date = date.fromisoformat(snapshot["end_date"])
        except (TypeError, ValueError):
            raise ItineraryCopyError("The field-note snapshot is invalid.") from None
        if not 1 <= (end_date - start_date).days + 1 <= 7:
            raise ItineraryCopyError("The field-note snapshot has an invalid date range.")

        # The unique operation key is the durable concurrency boundary. A savepoint
        # lets a losing concurrent insert recover without losing the surrounding request.
        try:
            async with self.session.begin_nested():
                existing = await self.session.scalar(select(ItineraryCopyOperation).where(
                    ItineraryCopyOperation.actor_id == actor_id,
                    ItineraryCopyOperation.source_post_id == post.id,
                    ItineraryCopyOperation.idempotency_key == idempotency_key,
                ))
                if existing is not None:
                    itinerary = await self.session.get(Itinerary, existing.itinerary_id)
                    return FieldNoteCopyResult(itinerary, True)
                itinerary = Itinerary(owner_id=actor_id, title=snapshot["title"], start_date=start_date, end_date=end_date, source_post_id=post.id)
                self.session.add(itinerary)
                await self.session.flush()
                await self._materialize_public_snapshot(itinerary, snapshot)
                await self._record_version(itinerary, actor_id)
                self.session.add(ItineraryCopyOperation(
                    actor_id=actor_id, source_post_id=post.id, itinerary_id=itinerary.id, idempotency_key=idempotency_key,
                ))
                await self.session.flush()
                await self.session.execute(update(type(post)).where(type(post).id == post.id).values(copy_count=type(post).copy_count + 1))
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(select(ItineraryCopyOperation).where(
                ItineraryCopyOperation.actor_id == actor_id,
                ItineraryCopyOperation.source_post_id == post.id,
                ItineraryCopyOperation.idempotency_key == idempotency_key,
            ))
            if existing is None:
                raise
            itinerary = await self.session.get(Itinerary, existing.itinerary_id)
            if itinerary is None:
                raise ItineraryCopyError("The original copy is unavailable.")
            return FieldNoteCopyResult(itinerary, True)
        await self.session.commit()
        await self.session.refresh(post)
        return FieldNoteCopyResult(itinerary, False)

    async def create_manual_plan(
        self, owner_id: str, *, title: str | None, start_date: date, end_date: date, destination: dict[str, str]
    ) -> Itinerary:
        duration = (end_date - start_date).days + 1
        if not 1 <= duration <= 7:
            raise ValueError("An itinerary must span one to seven days.")
        itinerary = Itinerary(
            owner_id=owner_id,
            title=title.strip() if title and title.strip() else f"{destination['name']}行程",
            start_date=start_date,
            end_date=end_date,
        )
        self.session.add(itinerary)
        await self.session.flush()
        for display_order in range(duration):
            self.session.add(ItineraryDay(
                itinerary_id=itinerary.id,
                day_date=date.fromordinal(start_date.toordinal() + display_order),
                display_order=display_order,
            ))
        await self.session.flush()
        snapshot = await self._snapshot(itinerary)
        snapshot["destination"] = dict(destination)
        self.session.add(ItineraryVersion(
            itinerary_id=itinerary.id,
            version=itinerary.version,
            snapshot=snapshot,
            created_by=owner_id,
        ))
        await self.session.commit()
        return itinerary

    async def create_companion_activity_itinerary(
        self,
        owner_id: str,
        *,
        title: str,
        activity_date: date,
        starts_at: datetime,
        ends_at: datetime,
        poi_id: str,
        city_code: str,
    ) -> Itinerary:
        """Materialize a verified one-day activity without committing the caller's transaction."""
        verification = await self.map_service.verify_poi(poi_id)
        if isinstance(verification, MapUnavailable):
            raise ValueError("The selected place could not be verified.")
        if verification.adcode and not _same_city_code(city_code, verification.adcode):
            raise ValueError("The selected place is outside the activity city.")

        itinerary = Itinerary(owner_id=owner_id, title=title, start_date=activity_date, end_date=activity_date)
        self.session.add(itinerary)
        await self.session.flush()
        day = ItineraryDay(itinerary_id=itinerary.id, day_date=activity_date, display_order=0)
        self.session.add(day)
        await self.session.flush()
        self.session.add(ItineraryEvent(
            day_id=day.id,
            poi_id=verification.id,
            poi_snapshot={
                "name": verification.name,
                "address": verification.address,
                "location": {"longitude": verification.location[0], "latitude": verification.location[1]},
                "city": verification.city,
                "type_name": verification.type_name,
                "source_updated_at": verification.source_updated_at,
            },
            starts_at=starts_at,
            ends_at=ends_at,
            display_order=0,
        ))
        await self.session.flush()
        await self._record_version(itinerary, owner_id)
        return itinerary

    async def get_itinerary(self, itinerary_id: str, actor_id: str) -> Itinerary | None:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None or not await self._can_read(itinerary, actor_id):
            return None
        return itinerary

    async def list_itineraries(self, actor_id: str) -> list[Itinerary]:
        collaborator_ids = select(TripCollaborator.itinerary_id).where(
            TripCollaborator.user_id == actor_id,
            TripCollaborator.status == "accepted",
        )
        statement = (
            select(Itinerary)
            .where(or_(Itinerary.owner_id == actor_id, Itinerary.id.in_(collaborator_ids)))
            .order_by(Itinerary.updated_at.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def get_snapshot(self, itinerary: Itinerary) -> dict[str, Any]:
        return await self._snapshot(itinerary)

    async def delete_itinerary(self, itinerary_id: str, actor_id: str) -> None:
        itinerary = await self.session.scalar(select(Itinerary).where(Itinerary.id == itinerary_id).with_for_update())
        if itinerary is None:
            raise ItineraryError("ITINERARY_NOT_FOUND", "The itinerary is unavailable.")
        if itinerary.owner_id != actor_id:
            raise ItineraryError("FORBIDDEN", "Only the itinerary owner can delete it.")
        active_companion = await self.session.scalar(select(CompanionRequest.id).where(
            CompanionRequest.itinerary_id == itinerary.id,
            CompanionRequest.status.in_(("open", "full", "closed")),
        ))
        if active_companion is not None:
            raise ItineraryError("COMPANION_PLAN_ACTIVE", "An active companion plan protects this itinerary.")

        day_ids = select(ItineraryDay.id).where(ItineraryDay.itinerary_id == itinerary.id)
        await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id.in_(day_ids)))
        await self.session.execute(delete(RouteCalculationJob).where(RouteCalculationJob.itinerary_id == itinerary.id))
        await self.session.execute(delete(ItineraryEvent).where(ItineraryEvent.day_id.in_(day_ids)))
        await self.session.execute(delete(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id))
        await self.session.execute(delete(ExportTask).where(ExportTask.itinerary_id == itinerary.id))
        version_ids = select(ItineraryVersion.id).where(ItineraryVersion.itinerary_id == itinerary.id)
        await self.session.execute(update(Post).where(
            or_(Post.itinerary_id == itinerary.id, Post.itinerary_version_id.in_(version_ids))
        ).values(itinerary_id=None, itinerary_version_id=None))
        await self.session.execute(update(CompanionRequest).where(CompanionRequest.itinerary_id == itinerary.id).values(itinerary_id=None))
        await self.session.execute(update(GenerationJob).where(GenerationJob.target_itinerary_id == itinerary.id).values(target_itinerary_id=None))
        await self.session.execute(delete(TripOperation).where(TripOperation.itinerary_id == itinerary.id))
        await self.session.execute(delete(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id))
        await self.session.execute(delete(TripCollaborator).where(TripCollaborator.itinerary_id == itinerary.id))
        await self.session.execute(delete(TripShareToken).where(TripShareToken.itinerary_id == itinerary.id))
        await self.session.execute(delete(ItineraryCopyOperation).where(ItineraryCopyOperation.itinerary_id == itinerary.id))
        await self.session.delete(itinerary)
        await self.session.commit()

    async def get_access_role(self, itinerary: Itinerary, actor_id: str) -> str | None:
        if itinerary.owner_id == actor_id:
            return "owner"
        collaborator = await self.session.scalar(select(TripCollaborator).where(
            TripCollaborator.itinerary_id == itinerary.id,
            TripCollaborator.user_id == actor_id,
            TripCollaborator.status == "accepted",
        ))
        return collaborator.role if collaborator else None

    async def list_versions(self, itinerary_id: str, actor_id: str) -> list[dict[str, Any]] | None:
        itinerary = await self.get_itinerary(itinerary_id, actor_id)
        if itinerary is None:
            return None
        versions = list((await self.session.scalars(
            select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id).order_by(ItineraryVersion.version.desc())
        )).all())
        sources = await self._version_sources(itinerary.id)
        return [self._version_response(version, sources.get(version.version, "initial")) for version in versions]

    async def get_version(self, itinerary_id: str, version_no: int, actor_id: str) -> dict[str, Any] | None:
        itinerary = await self.get_itinerary(itinerary_id, actor_id)
        if itinerary is None:
            return None
        version = await self.session.scalar(select(ItineraryVersion).where(
            ItineraryVersion.itinerary_id == itinerary.id,
            ItineraryVersion.version == version_no,
        ))
        if version is None:
            return None
        sources = await self._version_sources(itinerary.id)
        return self._version_response(version, sources.get(version.version, "initial"), include_snapshot=True)

    async def create_share_token(self, itinerary_id: str, actor_id: str, *, expires_at: datetime | None) -> tuple[TripShareToken, str] | None:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None or itinerary.owner_id != actor_id:
            return None
        if expires_at is not None:
            if expires_at.tzinfo is None:
                raise ValueError("expires_at must include a timezone.")
            if expires_at <= datetime.now(timezone.utc):
                raise ValueError("expires_at must be in the future.")
        token = token_urlsafe(32)
        share_token = TripShareToken(
            itinerary_id=itinerary.id,
            token_hash=sha256(token.encode()).hexdigest(),
            expires_at=expires_at,
        )
        self.session.add(share_token)
        await self.session.commit()
        return share_token, token

    async def revoke_share_token(self, itinerary_id: str, token_id: str, actor_id: str) -> bool:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        share_token = await self.session.get(TripShareToken, token_id)
        if itinerary is None or itinerary.owner_id != actor_id or share_token is None or share_token.itinerary_id != itinerary_id:
            return False
        if share_token.revoked_at is None:
            share_token.revoked_at = datetime.now(timezone.utc)
            await self.session.commit()
        return True

    async def get_shared_itinerary(self, itinerary_id: str, token: str) -> Itinerary | None:
        token_hash = sha256(token.encode()).hexdigest()
        share_token = await self.session.scalar(select(TripShareToken).where(
            TripShareToken.itinerary_id == itinerary_id,
            TripShareToken.token_hash == token_hash,
            TripShareToken.revoked_at.is_(None),
        ))
        if share_token is None or self._is_expired(share_token.expires_at):
            return None
        return await self.session.get(Itinerary, itinerary_id)

    @staticmethod
    def _is_expired(expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    async def invite_collaborator(self, itinerary_id: str, actor_id: str, *, user_id: str, role: str) -> TripCollaborator | None:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None or itinerary.owner_id != actor_id or user_id == actor_id:
            return None
        if await self.session.get(User, user_id) is None:
            return None
        collaborator = await self.session.scalar(select(TripCollaborator).where(
            TripCollaborator.itinerary_id == itinerary_id, TripCollaborator.user_id == user_id,
        ))
        if collaborator is None:
            collaborator = TripCollaborator(itinerary_id=itinerary_id, user_id=user_id, role=role, status="pending")
            self.session.add(collaborator)
        else:
            collaborator.role = role
            collaborator.status = "pending"
        await self.session.commit()
        return collaborator

    async def update_collaborator(self, itinerary_id: str, collaborator_id: str, actor_id: str, *, role: str | None, invite_status: str | None) -> TripCollaborator | None:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        collaborator = await self.session.get(TripCollaborator, collaborator_id)
        if itinerary is None or itinerary.owner_id != actor_id or collaborator is None or collaborator.itinerary_id != itinerary_id:
            return None
        if role is not None:
            collaborator.role = role
        if invite_status is not None:
            collaborator.status = invite_status
        await self.session.commit()
        return collaborator

    async def accept_collaborator(self, itinerary_id: str, collaborator_id: str, actor_id: str) -> TripCollaborator | None:
        collaborator = await self.session.get(TripCollaborator, collaborator_id)
        if collaborator is None or collaborator.itinerary_id != itinerary_id or collaborator.user_id != actor_id or collaborator.status not in {"pending", "accepted"}:
            return None
        if collaborator.status == "pending":
            collaborator.status = "accepted"
            await self.session.commit()
        return collaborator

    async def apply_operation(
        self, itinerary_id: str, actor_id: str, *, base_version: int, operation_id: str, operation_type: str, payload: dict[str, Any]
    ) -> OperationResult:
        itinerary = await self.session.scalar(select(Itinerary).where(Itinerary.id == itinerary_id).with_for_update())
        if itinerary is None:
            return OperationResult("NOT_FOUND")
        if not await self._can_edit(itinerary, actor_id):
            return OperationResult("FORBIDDEN", current_version=itinerary.version)

        recorded = await self.session.scalar(
            select(TripOperation).where(TripOperation.itinerary_id == itinerary_id, TripOperation.operation_id == operation_id)
        )
        if recorded is not None:
            return OperationResult("APPLIED", recorded.result_version, recorded.result_snapshot, idempotent=True)
        if base_version != itinerary.version:
            return OperationResult("VERSION_CONFLICT", current_version=itinerary.version, snapshot=await self._snapshot(itinerary))

        result = await self._mutate(itinerary, actor_id, operation_type, payload)
        if result is not None:
            return result
        itinerary.version += 1
        snapshot = await self._record_version(itinerary, actor_id)
        self.session.add(
            TripOperation(
                itinerary_id=itinerary.id,
                operation_id=operation_id,
                actor_id=actor_id,
                operation_type=operation_type,
                base_version=base_version,
                result_version=itinerary.version,
                result_snapshot=snapshot,
            )
        )
        await self.session.commit()
        route_job = await self._latest_route_job(itinerary.id, str(payload.get("day_id", ""))) if operation_type == "recalculate_route" else None
        return OperationResult("APPLIED", itinerary.version, snapshot, route_job=route_job)

    async def create_version(self, itinerary_id: str, actor_id: str) -> OperationResult:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None:
            return OperationResult("NOT_FOUND")
        if not await self._can_edit(itinerary, actor_id):
            return OperationResult("FORBIDDEN", current_version=itinerary.version)
        existing = await self.session.scalar(
            select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary.id, ItineraryVersion.version == itinerary.version)
        )
        snapshot = existing.snapshot if existing else await self._record_version(itinerary, actor_id)
        await self.session.commit()
        return OperationResult("APPLIED", itinerary.version, snapshot)

    async def restore_version(self, itinerary_id: str, actor_id: str, *, base_version: int, version: int, operation_id: str) -> OperationResult:
        itinerary = await self.session.scalar(select(Itinerary).where(Itinerary.id == itinerary_id).with_for_update())
        if itinerary is None:
            return OperationResult("NOT_FOUND")
        if not await self._can_edit(itinerary, actor_id):
            return OperationResult("FORBIDDEN", current_version=itinerary.version)
        recorded = await self.session.scalar(
            select(TripOperation).where(TripOperation.itinerary_id == itinerary_id, TripOperation.operation_id == operation_id)
        )
        if recorded is not None:
            return OperationResult("APPLIED", recorded.result_version, recorded.result_snapshot, idempotent=True)
        if base_version != itinerary.version:
            return OperationResult("VERSION_CONFLICT", itinerary.version, await self._snapshot(itinerary))
        source = await self.session.scalar(
            select(ItineraryVersion).where(ItineraryVersion.itinerary_id == itinerary_id, ItineraryVersion.version == version)
        )
        if source is None:
            return OperationResult("NOT_FOUND", itinerary.version)
        await self._replace_snapshot(itinerary, source.snapshot)
        itinerary.version += 1
        snapshot = await self._record_version(itinerary, actor_id)
        self.session.add(TripOperation(
            itinerary_id=itinerary.id, operation_id=operation_id, actor_id=actor_id, operation_type="restore_version",
            base_version=base_version, result_version=itinerary.version, result_snapshot=snapshot,
        ))
        await self.session.commit()
        return OperationResult("APPLIED", itinerary.version, snapshot)

    async def _can_edit(self, itinerary: Itinerary, actor_id: str) -> bool:
        if itinerary.owner_id == actor_id:
            return True
        collaborator = await self.session.scalar(select(TripCollaborator).where(
            TripCollaborator.itinerary_id == itinerary.id, TripCollaborator.user_id == actor_id,
            TripCollaborator.role == "editor", TripCollaborator.status == "accepted",
        ))
        return collaborator is not None

    async def can_export(self, itinerary: Itinerary, actor_id: str) -> bool:
        """Exports use the same current owner/editor boundary as itinerary edits."""
        return await self._can_edit(itinerary, actor_id)

    async def _can_read(self, itinerary: Itinerary, actor_id: str) -> bool:
        if itinerary.owner_id == actor_id:
            return True
        collaborator = await self.session.scalar(select(TripCollaborator).where(
            TripCollaborator.itinerary_id == itinerary.id,
            TripCollaborator.user_id == actor_id,
            TripCollaborator.status == "accepted",
        ))
        return collaborator is not None

    async def _mutate(self, itinerary: Itinerary, actor_id: str, operation_type: str, payload: dict[str, Any]) -> OperationResult | None:
        if operation_type == "apply_ai_preview":
            return await self._apply_ai_preview(itinerary, actor_id, payload)
        if operation_type == "add_day":
            day_date = date.fromisoformat(str(payload["day_date"]))
            exists = await self.session.scalar(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id, ItineraryDay.day_date == day_date))
            if exists is not None:
                raise ValueError("An itinerary day already exists for this date.")
            itinerary.start_date = min(itinerary.start_date, day_date)
            itinerary.end_date = max(itinerary.end_date, day_date)
            display_order = int((await self.session.scalar(select(func.coalesce(func.max(ItineraryDay.display_order), -1)).where(ItineraryDay.itinerary_id == itinerary.id))) + 1)
            self.session.add(ItineraryDay(itinerary_id=itinerary.id, day_date=day_date, display_order=display_order))
            await self.session.flush()
            return None
        if operation_type == "remove_day":
            day = await self.session.get(ItineraryDay, str(payload.get("day_id", "")))
            if day is None or day.itinerary_id != itinerary.id:
                return OperationResult("NOT_FOUND", itinerary.version)
            await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id == day.id))
            await self.session.execute(delete(RouteCalculationJob).where(RouteCalculationJob.day_id == day.id))
            await self.session.execute(delete(ItineraryEvent).where(ItineraryEvent.day_id == day.id))
            await self.session.delete(day)
            await self.session.flush()
            remaining_days = list((await self.session.scalars(
                select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id).order_by(ItineraryDay.day_date, ItineraryDay.id)
            )).all())
            temporary_base = len(remaining_days) + 1
            for order, remaining in enumerate(remaining_days):
                remaining.display_order = temporary_base + order
            await self.session.flush()
            for order, remaining in enumerate(remaining_days):
                remaining.display_order = order
            if remaining_days:
                itinerary.start_date = min(day.day_date for day in remaining_days)
                itinerary.end_date = max(day.day_date for day in remaining_days)
            await self.session.flush()
            return None
        if operation_type == "add_event":
            verification = await self.map_service.verify_poi(str(payload.get("poi_id", "")))
            if isinstance(verification, MapUnavailable):
                return OperationResult("MAP_UNAVAILABLE", itinerary.version, await self._snapshot(itinerary))
            day = await self.session.get(ItineraryDay, str(payload.get("day_id", "")))
            if day is None or day.itinerary_id != itinerary.id:
                return OperationResult("NOT_FOUND", itinerary.version)
            display_order = int((await self.session.scalar(
                select(func.coalesce(func.max(ItineraryEvent.display_order), -1)).where(ItineraryEvent.day_id == day.id)
            )) + 1)
            self.session.add(ItineraryEvent(
                day_id=day.id,
                poi_id=verification.id,
                poi_snapshot={
                    "name": verification.name,
                    "address": verification.address,
                    "location": {"longitude": verification.location[0], "latitude": verification.location[1]},
                    "city": verification.city,
                    "type_name": verification.type_name,
                    "source_updated_at": verification.source_updated_at,
                },
                display_order=display_order,
            ))
            await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id == day.id))
            await self.session.flush()
            return None
        if operation_type == "recalculate_route":
            day = await self.session.get(ItineraryDay, str(payload.get("day_id", "")))
            if day is None or day.itinerary_id != itinerary.id:
                return OperationResult("NOT_FOUND", itinerary.version)
            events = list((await self.session.scalars(
                select(ItineraryEvent).where(ItineraryEvent.day_id == day.id).order_by(ItineraryEvent.display_order)
            )).all())
            job = RouteCalculationJob(
                itinerary_id=itinerary.id,
                day_id=day.id,
                requested_by=actor_id,
                event_ids=[event.id for event in events],
            )
            self.session.add(job)
            await self.session.flush()
            self.session.add(OutboxEvent(
                event_type="itinerary.route_calculation_requested",
                aggregate_type="itinerary",
                aggregate_id=itinerary.id,
                trace_id=new_uuid(),
                payload_json={"route_calculation_job_id": job.id},
            ))
            return None
        event = await self.session.get(ItineraryEvent, str(payload.get("event_id", "")))
        if event is None:
            return OperationResult("NOT_FOUND", itinerary.version)
        day = await self.session.get(ItineraryDay, event.day_id)
        if day is None or day.itinerary_id != itinerary.id:
            return OperationResult("NOT_FOUND", itinerary.version)
        if operation_type == "remove_event":
            await self.session.delete(event)
            await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id == day.id))
            await self.session.flush()
            return None
        if operation_type == "update_event":
            if "notes" in payload:
                event.notes = str(payload["notes"]) if payload["notes"] is not None else None
            if "starts_at" in payload:
                event.starts_at = payload["starts_at"]
            if "ends_at" in payload:
                event.ends_at = payload["ends_at"]
            return None
        if operation_type == "reorder_event":
            direction = str(payload.get("direction", ""))
            if direction not in {"up", "down"}:
                raise ValueError("direction must be up or down.")
            events = list((await self.session.scalars(
                select(ItineraryEvent).where(ItineraryEvent.day_id == day.id).order_by(ItineraryEvent.display_order)
            )).all())
            index = next((index for index, item in enumerate(events) if item.id == event.id), -1)
            target_index = index - 1 if direction == "up" else index + 1
            if index < 0 or target_index < 0 or target_index >= len(events):
                return None
            reordered = events.copy()
            moved = reordered.pop(index)
            reordered.insert(target_index, moved)
            temporary_base = max((item.display_order for item in events), default=-1) + len(events) + 1
            for temporary_index, item in enumerate(events):
                item.display_order = temporary_base + temporary_index
            await self.session.flush()
            for display_order, item in enumerate(reordered):
                item.display_order = display_order
            await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id == day.id))
            await self.session.flush()
            return None
        raise ValueError("Unsupported itinerary operation.")

    async def _apply_ai_preview(self, itinerary: Itinerary, actor_id: str, payload: dict[str, Any]) -> OperationResult | None:
        preview_base_version = payload.get("base_version")
        if preview_base_version is not None and preview_base_version != itinerary.version:
            return OperationResult("VERSION_CONFLICT", itinerary.version, await self._snapshot(itinerary))
        draft = payload.get("draft")
        if not isinstance(draft, dict) or not isinstance(draft.get("days"), list) or not isinstance(draft.get("title"), str):
            return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
        days = draft["days"]
        expected_dates = [itinerary.start_date.fromordinal(itinerary.start_date.toordinal() + offset) for offset in range((itinerary.end_date - itinerary.start_date).days + 1)]
        if len(days) != len(expected_dates):
            return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
        seen_dates: set[date] = set()
        parsed_days: list[tuple[date, list[dict[str, Any]]]] = []
        for stored_day in days:
            if not isinstance(stored_day, dict) or not isinstance(stored_day.get("date"), str) or not isinstance(stored_day.get("activities"), list):
                return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
            try:
                day_date = date.fromisoformat(stored_day["date"])
            except ValueError:
                return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
            if day_date in seen_dates or not itinerary.start_date <= day_date <= itinerary.end_date:
                return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
            seen_dates.add(day_date)
            activities: list[dict[str, Any]] = []
            for activity in stored_day["activities"]:
                if not isinstance(activity, dict):
                    return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
                poi_id = activity.get("poi_id")
                poi_name = activity.get("poi_name")
                longitude = activity.get("longitude")
                latitude = activity.get("latitude")
                title = activity.get("title")
                if not isinstance(poi_id, str) or not poi_id or not isinstance(poi_name, str) or not isinstance(title, str):
                    return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
                if not all(isinstance(value, (int, float)) for value in (longitude, latitude)):
                    return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
                activities.append(activity)
            parsed_days.append((day_date, activities))
        if [day_date for day_date, _ in parsed_days] != expected_dates:
            return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))

        day_ids = select(ItineraryDay.id).where(ItineraryDay.itinerary_id == itinerary.id)
        await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id.in_(day_ids)))
        await self.session.execute(delete(ItineraryEvent).where(ItineraryEvent.day_id.in_(day_ids)))
        await self.session.execute(delete(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id))
        for display_order, (day_date, activities) in enumerate(parsed_days):
            day = ItineraryDay(itinerary_id=itinerary.id, day_date=day_date, display_order=display_order)
            self.session.add(day)
            await self.session.flush()
            for event_order, activity in enumerate(activities):
                poi_id = activity.get("poi_id")
                poi_name = activity.get("poi_name")
                longitude = activity.get("longitude")
                latitude = activity.get("latitude")
                title = activity.get("title")
                if not isinstance(poi_id, str) or not poi_id or not isinstance(poi_name, str) or not isinstance(title, str):
                    return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
                if not all(isinstance(value, (int, float)) for value in (longitude, latitude)):
                    return OperationResult("PREVIEW_INVALID", itinerary.version, await self._snapshot(itinerary))
                self.session.add(ItineraryEvent(
                    day_id=day.id,
                    poi_id=poi_id,
                    poi_snapshot={
                        "name": poi_name,
                        "location": {"longitude": float(longitude), "latitude": float(latitude)},
                        "source": "ai_preview_verified",
                    },
                    display_order=event_order,
                    notes=title,
                ))
            await self.session.flush()
            if activities:
                events = list((await self.session.scalars(select(ItineraryEvent).where(ItineraryEvent.day_id == day.id).order_by(ItineraryEvent.display_order))).all())
                job = RouteCalculationJob(
                    itinerary_id=itinerary.id,
                    day_id=day.id,
                    requested_by=actor_id,
                    event_ids=[event.id for event in events],
                )
                self.session.add(job)
                await self.session.flush()
                self.session.add(OutboxEvent(
                    event_type="itinerary.route_calculation_requested",
                    aggregate_type="itinerary",
                    aggregate_id=itinerary.id,
                    trace_id=new_uuid(),
                    payload_json={"route_calculation_job_id": job.id},
                ))
        itinerary.title = draft["title"].strip()[:160]
        generation_job_id = payload.get("generation_job_id")
        poi_ids = sorted({activity["poi_id"] for _, activities in parsed_days for activity in activities})
        if isinstance(generation_job_id, str) and poi_ids:
            self.session.add(OutboxEvent(
                event_type="ai.confirmed_preview_poi_discovery_requested",
                aggregate_type="itinerary",
                aggregate_id=itinerary.id,
                trace_id=new_uuid(),
                payload_json={"generation_job_id": generation_job_id, "poi_ids": poi_ids},
            ))
        return None

    async def _record_version(self, itinerary: Itinerary, actor_id: str) -> dict[str, Any]:
        snapshot = await self._snapshot(itinerary)
        self.session.add(ItineraryVersion(itinerary_id=itinerary.id, version=itinerary.version, snapshot=snapshot, created_by=actor_id))
        await self.session.flush()
        return snapshot

    async def _version_sources(self, itinerary_id: str) -> dict[int, str]:
        operations = list((await self.session.scalars(select(TripOperation).where(
            TripOperation.itinerary_id == itinerary_id,
        ))).all())
        return {operation.result_version: operation.operation_type for operation in operations}

    @staticmethod
    def _version_response(version: ItineraryVersion, source: str, *, include_snapshot: bool = False) -> dict[str, Any]:
        response = {
            "id": version.id,
            "version_no": version.version,
            "source": source,
            "created_at": version.created_at,
        }
        if include_snapshot:
            response["snapshot"] = dict(version.snapshot)
        return response

    async def _snapshot(self, itinerary: Itinerary) -> dict[str, Any]:
        days = list((await self.session.scalars(select(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id).order_by(ItineraryDay.display_order))).all())
        return {
            "title": itinerary.title, "start_date": itinerary.start_date.isoformat(), "end_date": itinerary.end_date.isoformat(),
            "days": [{"id": day.id, "day_date": day.day_date.isoformat(), "display_order": day.display_order,
                "events": [{"id": event.id, "poi_id": event.poi_id, "poi_snapshot": event.poi_snapshot,
                    "starts_at": event.starts_at.isoformat() if event.starts_at else None, "ends_at": event.ends_at.isoformat() if event.ends_at else None,
                    "display_order": event.display_order, "notes": event.notes}
                    for event in (await self.session.scalars(select(ItineraryEvent).where(ItineraryEvent.day_id == day.id).order_by(ItineraryEvent.display_order))).all()],
                "route_segments": [{"display_order": segment.display_order, "travel_mode": segment.travel_mode,
                    "distance_meters": segment.distance_meters, "duration_seconds": segment.duration_seconds,
                    "route_snapshot": segment.route_snapshot}
                    for segment in (await self.session.scalars(select(RouteSegment).where(RouteSegment.day_id == day.id).order_by(RouteSegment.display_order))).all()],
                "route_calculation": self._route_job_snapshot(await self._latest_route_job(itinerary.id, day.id))}
                for day in days],
        }

    async def _replace_snapshot(self, itinerary: Itinerary, snapshot: dict[str, Any]) -> None:
        day_ids = select(ItineraryDay.id).where(ItineraryDay.itinerary_id == itinerary.id)
        await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id.in_(day_ids)))
        await self.session.execute(delete(ItineraryEvent).where(ItineraryEvent.day_id.in_(day_ids)))
        await self.session.execute(delete(ItineraryDay).where(ItineraryDay.itinerary_id == itinerary.id))
        itinerary.title = str(snapshot["title"])
        for stored_day in snapshot["days"]:
            day = ItineraryDay(itinerary_id=itinerary.id, day_date=date.fromisoformat(stored_day["day_date"]), display_order=stored_day["display_order"])
            self.session.add(day)
            await self.session.flush()
            for stored_event in stored_day["events"]:
                self.session.add(ItineraryEvent(day_id=day.id, poi_id=stored_event["poi_id"], poi_snapshot=stored_event["poi_snapshot"],
                    starts_at=datetime.fromisoformat(stored_event["starts_at"]) if stored_event["starts_at"] else None,
                    ends_at=datetime.fromisoformat(stored_event["ends_at"]) if stored_event["ends_at"] else None,
                    display_order=stored_event["display_order"], notes=stored_event["notes"]))
            for stored_segment in stored_day.get("route_segments", []):
                self.session.add(RouteSegment(
                    day_id=day.id,
                    display_order=stored_segment["display_order"],
                    travel_mode=stored_segment["travel_mode"],
                    distance_meters=stored_segment["distance_meters"],
                    duration_seconds=stored_segment["duration_seconds"],
                    route_snapshot=stored_segment["route_snapshot"],
                ))
        await self.session.flush()

    async def _materialize_public_snapshot(self, itinerary: Itinerary, snapshot: dict[str, Any]) -> None:
        for stored_day in snapshot["days"]:
            day = ItineraryDay(itinerary_id=itinerary.id, day_date=date.fromisoformat(stored_day["day_date"]), display_order=stored_day["display_order"])
            self.session.add(day)
            await self.session.flush()
            for stored_event in stored_day["events"]:
                self.session.add(ItineraryEvent(
                    day_id=day.id, poi_id=stored_event["poi_id"], poi_snapshot=stored_event["poi_snapshot"],
                    starts_at=datetime.fromisoformat(stored_event["starts_at"]) if stored_event["starts_at"] else None,
                    ends_at=datetime.fromisoformat(stored_event["ends_at"]) if stored_event["ends_at"] else None,
                    display_order=stored_event["display_order"], notes=stored_event["notes"],
                ))
        await self.session.flush()

    async def get_route_calculation_job(self, itinerary_id: str, job_id: str, actor_id: str) -> RouteCalculationJob | None:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None or not await self._can_read(itinerary, actor_id):
            return None
        job = await self.session.get(RouteCalculationJob, job_id)
        return job if job is not None and job.itinerary_id == itinerary_id else None

    async def process_route_calculation(self, job_id: str) -> None:
        job = await self.session.get(RouteCalculationJob, job_id)
        if job is None or job.status in {"completed", "failed"}:
            return
        job.status = "calculating"
        day = await self.session.get(ItineraryDay, job.day_id)
        if day is None:
            job.status = "failed"
            job.error_code = "DAY_NOT_FOUND"
            job.completed_at = utc_now()
            return
        events = list((await self.session.scalars(
            select(ItineraryEvent).where(ItineraryEvent.day_id == day.id).order_by(ItineraryEvent.display_order)
        )).all())
        if [event.id for event in events] != job.event_ids:
            job.status = "failed"
            job.error_code = "STALE_ROUTE_REQUEST"
            job.completed_at = utc_now()
            return
        planned_routes = []
        for origin, destination in zip(events, events[1:]):
            try:
                origin_location = origin.poi_snapshot["location"]
                destination_location = destination.poi_snapshot["location"]
                route = await self.map_service.plan_driving_route(
                    (float(origin_location["longitude"]), float(origin_location["latitude"])),
                    (float(destination_location["longitude"]), float(destination_location["latitude"])),
                )
            except (KeyError, TypeError, ValueError):
                route = MapUnavailable()
            if isinstance(route, MapUnavailable):
                job.status = "failed"
                job.error_code = route.code
                job.completed_at = utc_now()
                return
            planned_routes.append(route)
        await self.session.execute(delete(RouteSegment).where(RouteSegment.day_id == day.id))
        for display_order, route in enumerate(planned_routes):
            self.session.add(RouteSegment(
                day_id=day.id,
                display_order=display_order,
                travel_mode="driving",
                distance_meters=route.distance_meters,
                duration_seconds=route.duration_seconds,
                route_snapshot={"polyline": [{"longitude": longitude, "latitude": latitude} for longitude, latitude in route.polyline]},
            ))
        job.status = "completed"
        job.error_code = None
        job.completed_at = utc_now()

    async def _latest_route_job(self, itinerary_id: str, day_id: str) -> RouteCalculationJob | None:
        return await self.session.scalar(
            select(RouteCalculationJob).where(
                RouteCalculationJob.itinerary_id == itinerary_id,
                RouteCalculationJob.day_id == day_id,
            ).order_by(RouteCalculationJob.created_at.desc())
        )

    @staticmethod
    def _route_job_snapshot(job: RouteCalculationJob | None) -> dict[str, Any] | None:
        if job is None:
            return None
        return {"id": job.id, "status": job.status, "error_code": job.error_code}


def _same_city_code(expected: str, actual: str) -> bool:
    return expected == actual or (
        len(expected) == len(actual) == 6
        and expected.isdigit()
        and actual.isdigit()
        and expected[:4] == actual[:4]
    )


def _validate_public_field_note_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("title"), str) or not snapshot["title"].strip():
        raise ItineraryCopyError("The field-note snapshot is invalid.")
    if not isinstance(snapshot.get("start_date"), str) or not isinstance(snapshot.get("end_date"), str) or not isinstance(snapshot.get("days"), list) or not snapshot["days"]:
        raise ItineraryCopyError("The field-note snapshot is invalid.")
    try:
        date.fromisoformat(snapshot["start_date"])
        date.fromisoformat(snapshot["end_date"])
    except ValueError:
        raise ItineraryCopyError("The field-note snapshot is invalid.") from None
    has_event = False
    for day in snapshot["days"]:
        if not isinstance(day, dict) or not isinstance(day.get("day_date"), str) or not isinstance(day.get("display_order"), int) or not isinstance(day.get("events"), list):
            raise ItineraryCopyError("The field-note snapshot is invalid.")
        try:
            date.fromisoformat(day["day_date"])
        except ValueError:
            raise ItineraryCopyError("The field-note snapshot is invalid.") from None
        for event in day["events"]:
            if not isinstance(event, dict) or not isinstance(event.get("poi_id"), str) or not event["poi_id"] or not isinstance(event.get("poi_snapshot"), dict) or not isinstance(event.get("display_order"), int):
                raise ItineraryCopyError("The field-note snapshot is invalid.")
            if any(event.get(field) is not None and not isinstance(event.get(field), str) for field in ("starts_at", "ends_at", "notes")):
                raise ItineraryCopyError("The field-note snapshot is invalid.")
            for field in ("starts_at", "ends_at"):
                if event.get(field) is not None:
                    try:
                        datetime.fromisoformat(event[field])
                    except ValueError:
                        raise ItineraryCopyError("The field-note snapshot is invalid.") from None
            has_event = True
    if not has_event:
        raise ItineraryCopyError("The field-note snapshot must contain at least one stop.")
    return snapshot
