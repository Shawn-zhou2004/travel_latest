from __future__ import annotations

import secrets
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserRole
from app.modules.maps.service import AMapService, MapUnavailable
from app.modules.providers.models import Experience, ExperienceBooking, ExperienceReview, ExperienceSession, Provider, ProviderReview


class ProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message


class ProviderService:
    def __init__(self, session: AsyncSession, map_service: AMapService | None = None) -> None:
        self.session, self.map_service = session, map_service or AMapService()

    async def apply(self, actor_id: str, **data: object) -> Provider:
        provider = Provider(applicant_id=actor_id, **data)
        self.session.add(provider)
        await self.session.commit()
        return provider

    async def review(self, provider_id: str, actor_id: str, roles: list[str], status: str, reason: str) -> Provider:
        self._require_admin(roles)
        provider = await self._provider(provider_id)
        if provider.status != "pending_review":
            raise ProviderError("INVALID_PROVIDER_TRANSITION", "Only pending applications can be reviewed.")
        previous = provider.status
        provider.status, provider.review_reason, provider.reviewed_by, provider.reviewed_at = status, reason, actor_id, datetime.now(UTC)
        self.session.add(ProviderReview(provider_id=provider.id, actor_id=actor_id, previous_status=previous, result_status=status, reason=reason))
        if status == "approved":
            role = await self.session.scalar(
                select(UserRole).where(
                    UserRole.user_id == provider.applicant_id,
                    UserRole.role == "provider_admin",
                    UserRole.scope_key == provider.id,
                )
            )
            if role is None:
                self.session.add(UserRole(user_id=provider.applicant_id, role="provider_admin", scope_key=provider.id))
        await self.session.commit()
        return provider

    async def create_experience(self, provider_id: str, actor_id: str, roles: list[str], **data: object) -> Experience:
        await self._require_scope(provider_id, actor_id, roles)
        provider = await self._provider(provider_id)
        if provider.status != "approved":
            raise ProviderError("PROVIDER_NOT_APPROVED", "Only approved providers can create experiences.")
        poi = await self.map_service.verify_poi(str(data.pop("poi_id")))
        if isinstance(poi, MapUnavailable):
            raise ProviderError("MAP_UNAVAILABLE", "The experience location could not be verified.")
        experience = Experience(provider_id=provider_id, poi_id=poi.id, poi_name=poi.name, poi_address=poi.address, **data)
        self.session.add(experience)
        await self.session.commit()
        return experience

    async def create_session(self, experience_id: str, actor_id: str, roles: list[str], **data: object) -> ExperienceSession:
        experience = await self._experience(experience_id)
        await self._require_scope(experience.provider_id, actor_id, roles)
        session = ExperienceSession(experience_id=experience_id, **data)
        self.session.add(session)
        await self.session.commit()
        return session

    async def list_workspace_experiences(self, provider_id: str, actor_id: str, roles: list[str]) -> list[Experience]:
        await self._require_workspace_scope(provider_id, actor_id, roles, "PROVIDER_NOT_FOUND")
        return list(
            (
                await self.session.scalars(
                    select(Experience)
                    .where(Experience.provider_id == provider_id)
                    .order_by(Experience.created_at.desc(), Experience.id)
                )
            ).all()
        )

    async def get_workspace_experience(self, experience_id: str, actor_id: str, roles: list[str]) -> Experience:
        experience = await self._experience(experience_id)
        await self._require_workspace_scope(experience.provider_id, actor_id, roles, "EXPERIENCE_NOT_FOUND")
        return experience

    async def update_workspace_experience(
        self, experience_id: str, actor_id: str, roles: list[str], **data: object
    ) -> Experience:
        experience = await self.get_workspace_experience(experience_id, actor_id, roles)
        for field, value in data.items():
            setattr(experience, field, value)
        await self.session.commit()
        return experience

    async def list_workspace_sessions(self, experience_id: str, actor_id: str, roles: list[str]) -> list[ExperienceSession]:
        experience = await self.get_workspace_experience(experience_id, actor_id, roles)
        return list(
            (
                await self.session.scalars(
                    select(ExperienceSession)
                    .where(ExperienceSession.experience_id == experience.id)
                    .order_by(ExperienceSession.starts_at, ExperienceSession.id)
                )
            ).all()
        )

    async def list_workspace_bookings(
        self, provider_id: str, actor_id: str, roles: list[str], status: str | None
    ) -> list[tuple[ExperienceBooking, ExperienceSession, Experience]]:
        await self._require_workspace_scope(provider_id, actor_id, roles, "PROVIDER_NOT_FOUND")
        statement = (
            select(ExperienceBooking, ExperienceSession, Experience)
            .join(ExperienceSession, ExperienceSession.id == ExperienceBooking.experience_session_id)
            .join(Experience, Experience.id == ExperienceSession.experience_id)
            .where(Experience.provider_id == provider_id)
            .order_by(ExperienceSession.starts_at, ExperienceBooking.created_at)
        )
        if status is not None:
            if status not in {"reserved", "verified", "cancelled"}:
                raise ProviderError("BOOKING_STATUS_INVALID", "The booking status filter is invalid.")
            statement = statement.where(ExperienceBooking.status == status)
        return list((await self.session.execute(statement)).tuples().all())

    async def update_workspace_session(
        self, experience_id: str, session_id: str, actor_id: str, roles: list[str], **data: object
    ) -> ExperienceSession:
        await self.get_workspace_experience(experience_id, actor_id, roles)
        session = await self._session(session_id)
        if session.experience_id != experience_id:
            raise ProviderError("SESSION_NOT_FOUND", "The experience session is unavailable.")
        now = datetime.now(UTC)
        starts_at = session.starts_at if session.starts_at.tzinfo else session.starts_at.replace(tzinfo=UTC)
        if starts_at <= now:
            raise ProviderError("SESSION_IN_PAST", "Past sessions cannot be modified.")
        new_starts_at = data.get("starts_at")
        if isinstance(new_starts_at, datetime):
            normalized_start = new_starts_at if new_starts_at.tzinfo else new_starts_at.replace(tzinfo=UTC)
            if normalized_start <= now:
                raise ProviderError("SESSION_IN_PAST", "Sessions cannot be scheduled in the past.")
        capacity = data.get("capacity", session.capacity)
        if not isinstance(capacity, int) or capacity < session.reserved_count:
            raise ProviderError("SESSION_CAPACITY_BELOW_RESERVED", "Capacity cannot be lower than reserved places.")
        for field, value in data.items():
            setattr(session, field, value)
        await self.session.commit()
        return session

    async def book(self, actor_id: str, session_id: str, traveler_count: int) -> ExperienceBooking:
        session = await self.session.scalar(select(ExperienceSession).where(ExperienceSession.id == session_id).with_for_update())
        if session is None:
            raise ProviderError("SESSION_NOT_FOUND", "The experience session is unavailable.")
        if session.status != "scheduled":
            raise ProviderError("SESSION_UNAVAILABLE", "The experience session cannot accept reservations.")
        existing = await self.session.scalar(select(ExperienceBooking).where(ExperienceBooking.experience_session_id == session_id, ExperienceBooking.user_id == actor_id))
        if existing is not None:
            raise ProviderError("DUPLICATE_BOOKING", "You already have a reservation for this session.")
        if session.capacity - session.reserved_count < traveler_count:
            raise ProviderError("SESSION_CAPACITY_EXCEEDED", "There are not enough remaining places.")
        session.reserved_count += traveler_count
        booking = ExperienceBooking(experience_session_id=session_id, user_id=actor_id, traveler_count=traveler_count, verification_code=secrets.token_urlsafe(9)[:16])
        self.session.add(booking)
        await self.session.commit()
        return booking

    async def verify(self, booking_id: str, provider_id: str, actor_id: str, roles: list[str], code: str) -> ExperienceBooking:
        booking = await self._booking(booking_id)
        session = await self._session(booking.experience_session_id)
        experience = await self._experience(session.experience_id)
        if experience.provider_id != provider_id:
            raise ProviderError("BOOKING_NOT_FOUND", "The booking is unavailable.")
        await self._require_workspace_scope(provider_id, actor_id, roles, "BOOKING_NOT_FOUND")
        if booking.status != "reserved":
            raise ProviderError("BOOKING_NOT_VERIFIABLE", "This reservation has already been processed.")
        if not secrets.compare_digest(booking.verification_code, code):
            raise ProviderError("INVALID_VERIFICATION_CODE", "The verification code is invalid.")
        booking.status, booking.verified_at = "verified", datetime.now(UTC)
        await self.session.commit()
        return booking

    async def review_booking(self, booking_id: str, actor_id: str, rating: int, body: str) -> ExperienceReview:
        booking = await self._booking(booking_id)
        if booking.user_id != actor_id:
            raise ProviderError("FORBIDDEN", "Only the booking owner can write a review.")
        if booking.status != "verified":
            raise ProviderError("BOOKING_NOT_COMPLETED", "Only verified bookings can be reviewed.")
        if await self.session.scalar(select(ExperienceReview).where(ExperienceReview.booking_id == booking_id)):
            raise ProviderError("DUPLICATE_REVIEW", "This booking has already been reviewed.")
        review = ExperienceReview(booking_id=booking_id, user_id=actor_id, rating=rating, body=body)
        self.session.add(review)
        await self.session.commit()
        return review

    async def list_provider_applications(self, roles: list[str], status: str | None = None) -> list[Provider]:
        self._require_admin(roles)
        statement = select(Provider).order_by(Provider.created_at.desc())
        if status:
            statement = statement.where(Provider.status == status)
        return list((await self.session.scalars(statement)).all())

    async def list_public_experiences(self, provider_id: str | None, limit: int) -> list[tuple[Experience, Provider]]:
        statement = (
            select(Experience, Provider)
            .join(Provider, Provider.id == Experience.provider_id)
            .where(Experience.status == "published", Provider.status == "approved")
            .order_by(Experience.created_at.desc(), Experience.id)
            .limit(limit)
        )
        if provider_id is not None:
            statement = statement.where(Experience.provider_id == provider_id)
        return list((await self.session.execute(statement)).tuples().all())

    async def get_public_experience(self, experience_id: str) -> tuple[Experience, Provider, list[ExperienceSession]]:
        result = await self.session.execute(
            select(Experience, Provider)
            .join(Provider, Provider.id == Experience.provider_id)
            .where(
                Experience.id == experience_id,
                Experience.status == "published",
                Provider.status == "approved",
            )
        )
        item = result.tuples().one_or_none()
        if item is None:
            raise ProviderError("EXPERIENCE_NOT_FOUND", "The experience is unavailable.")
        experience, provider = item
        sessions = list(
            (
                await self.session.scalars(
                    select(ExperienceSession)
                    .where(
                        ExperienceSession.experience_id == experience.id,
                        ExperienceSession.status == "scheduled",
                        ExperienceSession.starts_at > datetime.now(UTC),
                    )
                    .order_by(ExperienceSession.starts_at, ExperienceSession.id)
                )
            ).all()
        )
        return experience, provider, sessions

    async def _require_scope(self, provider_id: str, actor_id: str, roles: list[str]) -> None:
        if not {"provider_admin", "provider_staff"}.intersection(roles):
            raise ProviderError("FORBIDDEN", "Provider staff role required.")
        membership = await self.session.scalar(select(UserRole).where(UserRole.user_id == actor_id, UserRole.role.in_(("provider_admin", "provider_staff")), UserRole.scope_key == provider_id))
        if membership is None:
            raise ProviderError("PROVIDER_SCOPE_FORBIDDEN", "You do not have access to this provider.")

    async def _require_workspace_scope(self, provider_id: str, actor_id: str, roles: list[str], not_found_code: str) -> None:
        try:
            await self._require_scope(provider_id, actor_id, roles)
        except ProviderError as error:
            if error.code == "PROVIDER_SCOPE_FORBIDDEN":
                raise ProviderError(not_found_code, "The resource is unavailable.") from error
            raise

    @staticmethod
    def _require_admin(roles: list[str]) -> None:
        if "platform_admin" not in roles:
            raise ProviderError("FORBIDDEN", "Platform admin role required.")

    async def _provider(self, provider_id: str) -> Provider:
        provider = await self.session.get(Provider, provider_id)
        if provider is None:
            raise ProviderError("PROVIDER_NOT_FOUND", "The provider is unavailable.")
        return provider

    async def _experience(self, experience_id: str) -> Experience:
        experience = await self.session.get(Experience, experience_id)
        if experience is None:
            raise ProviderError("EXPERIENCE_NOT_FOUND", "The experience is unavailable.")
        return experience

    async def _session(self, session_id: str) -> ExperienceSession:
        session = await self.session.get(ExperienceSession, session_id)
        if session is None:
            raise ProviderError("SESSION_NOT_FOUND", "The experience session is unavailable.")
        return session

    async def _booking(self, booking_id: str) -> ExperienceBooking:
        booking = await self.session.get(ExperienceBooking, booking_id)
        if booking is None:
            raise ProviderError("BOOKING_NOT_FOUND", "The booking is unavailable.")
        return booking
