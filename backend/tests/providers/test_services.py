import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.base import Base
from app.models.user import User, UserRole
from app.modules.maps.service import MapPOI
from app.modules.providers.service import ProviderError, ProviderService


class VerifiedMap:
    async def verify_poi(self, poi_id: str) -> MapPOI:
        return MapPOI(poi_id, "West Lake", "Hangzhou", (120.1, 30.2))


async def make_session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return AsyncSession(engine, expire_on_commit=False), engine


def test_application_review_scope_booking_verification_and_review() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            applicant, admin, outsider, traveler = (User(phone=phone) for phone in ("13800000000", "13900000000", "13700000000", "13600000000"))
            session.add_all([applicant, admin, outsider, traveler])
            await session.commit()
            service = ProviderService(session, VerifiedMap())
            provider = await service.apply(applicant.id, provider_type="guide", legal_name="Lake Tours", contact="13800000000", qualification_asset_ids=["asset-1"], claimed_poi_ids=[])
            assert provider.status == "pending_review"
            try:
                await service.review(provider.id, applicant.id, ["user"], "approved", "ok")
                assert False, "non-admin review must fail"
            except ProviderError as error:
                assert error.code == "FORBIDDEN"
            provider = await service.review(provider.id, admin.id, ["platform_admin"], "approved", "documents verified")
            assert provider.status == "approved" and provider.review_reason == "documents verified"
            assigned_roles = list(
                (await session.scalars(select(UserRole).where(UserRole.user_id == applicant.id, UserRole.scope_key == provider.id))).all()
            )
            assert [role.role for role in assigned_roles] == ["provider_admin"]
            experience = await service.create_experience(provider.id, applicant.id, ["provider_admin"], title="Sunset walk", description="A guided lakeside walk", poi_id="B001", price_amount="120.00", currency="CNY", cancellation_policy="24 hours", status="published")
            try:
                await service.create_session(experience.id, outsider.id, ["provider_staff"], starts_at=datetime.now(UTC) + timedelta(days=1), capacity=2, price_amount=None, currency=None)
                assert False, "outside provider staff must fail"
            except ProviderError as error:
                assert error.code == "PROVIDER_SCOPE_FORBIDDEN"
            scheduled = await service.create_session(experience.id, applicant.id, ["provider_admin"], starts_at=datetime.now(UTC) + timedelta(days=1), capacity=2, price_amount=None, currency=None)
            booking = await service.book(traveler.id, scheduled.id, 2)
            assert booking.status == "reserved" and scheduled.reserved_count == 2
            for count, expected in ((1, "DUPLICATE_BOOKING"),):
                try:
                    await service.book(traveler.id, scheduled.id, count)
                    assert False, "duplicate booking must fail"
                except ProviderError as error:
                    assert error.code == expected
            try:
                await service.verify(booking.id, provider.id, applicant.id, ["provider_admin"], "incorrect")
                assert False, "incorrect code must fail"
            except ProviderError as error:
                assert error.code == "INVALID_VERIFICATION_CODE"
            verified = await service.verify(booking.id, provider.id, applicant.id, ["provider_admin"], booking.verification_code)
            assert verified.status == "verified"
            try:
                await service.verify(booking.id, provider.id, applicant.id, ["provider_admin"], booking.verification_code)
                assert False, "verification must be once-only"
            except ProviderError as error:
                assert error.code == "BOOKING_NOT_VERIFIABLE"
            try:
                await service.review_booking(booking.id, outsider.id, 5, "Great")
                assert False, "only booking owner can review"
            except ProviderError as error:
                assert error.code == "FORBIDDEN"
            review = await service.review_booking(booking.id, traveler.id, 5, "Great")
            assert review.rating == 5
        finally:
            await session.close()
            await engine.dispose()
    asyncio.run(scenario())


def test_rejected_application_does_not_grant_role_and_approval_reuses_existing_role() -> None:
    async def scenario() -> None:
        session, engine = await make_session()
        try:
            applicant, admin = (User(phone=phone) for phone in ("13500000000", "13400000000"))
            session.add_all([applicant, admin])
            await session.commit()
            service = ProviderService(session, VerifiedMap())
            rejected = await service.apply(applicant.id, provider_type="guide", legal_name="Rejected Tours", contact="13500000000", qualification_asset_ids=[], claimed_poi_ids=[])
            await service.review(rejected.id, admin.id, ["platform_admin"], "rejected", "incomplete documents")
            assert await session.scalar(select(UserRole).where(UserRole.user_id == applicant.id, UserRole.scope_key == rejected.id)) is None

            approved = await service.apply(applicant.id, provider_type="guide", legal_name="Approved Tours", contact="13500000000", qualification_asset_ids=[], claimed_poi_ids=[])
            session.add(UserRole(user_id=applicant.id, role="provider_admin", scope_key=approved.id))
            await session.commit()
            await service.review(approved.id, admin.id, ["platform_admin"], "approved", "verified")
            roles = list(
                (await session.scalars(select(UserRole).where(UserRole.user_id == applicant.id, UserRole.scope_key == approved.id))).all()
            )
            assert [role.role for role in roles] == ["provider_admin"]
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())
