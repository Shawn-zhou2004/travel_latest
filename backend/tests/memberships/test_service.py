from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import AdminAction
from app.modules.memberships.models import MembershipPlan, UserEntitlement, UserMembership
from app.modules.memberships.schemas import MembershipGrantCreate, MembershipPlanCreate
from app.modules.memberships.service import MEMBERSHIP_ENTITLEMENT_UPDATED, MembershipError, MembershipService, effective_membership_status


@pytest.mark.anyio
async def test_admin_grant_is_idempotent_and_creates_entitlement_snapshots_and_events() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        admin = User(phone="13600000071")
        user = User(phone="13600000072")
        session.add_all((admin, user))
        await session.flush()
        service = MembershipService(session)
        plan = await service.create_plan(
            MembershipPlanCreate(code="traveler-plus", name="Traveler Plus", duration_days=30, entitlement_codes=["ai_quota", "priority_support"], price_amount="19.90", currency="CNY", generation_quota=10, assistant_quota=300),
            admin.id,
        )
        await service.publish_plan(plan.id, admin.id)
        valid_from = datetime.now(UTC) - timedelta(minutes=1)
        request = MembershipGrantCreate(user_id=user.id, plan_id=plan.id, valid_from=valid_from, reason="Manual recovery.")
        membership = await service.grant(request, admin.id, "grant-1")
        duplicate = await service.grant(request, admin.id, "grant-1")
        assert duplicate.id == membership.id
        assert membership.valid_until == valid_from + timedelta(days=30)
        snapshots = (await session.scalars(select(UserEntitlement).where(UserEntitlement.membership_id == membership.id))).all()
        assert {item.entitlement_code for item in snapshots} == {"ai_quota", "priority_support"}
        events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == membership.id))).all()
        assert len(events) == 1
        assert events[0].event_type == MEMBERSHIP_ENTITLEMENT_UPDATED
        assert events[0].payload_json["status"] == "active"
        audit = await session.scalar(select(AdminAction).where(AdminAction.target_id == membership.id))
        assert audit is not None
        assert audit.action == "membership.granted"
        assert audit.reason == "Manual recovery."
        conflicting_plan = await service.create_plan(
            MembershipPlanCreate(code="traveler-basic", name="Traveler Basic", duration_days=7, entitlement_codes=["maps"], price_amount="9.90", currency="CNY", generation_quota=1, assistant_quota=20),
            admin.id,
        )
        await service.publish_plan(conflicting_plan.id, admin.id)
        with pytest.raises(MembershipError, match="Idempotency-Key"):
            await service.grant(
                MembershipGrantCreate(user_id=user.id, plan_id=conflicting_plan.id, reason="Other request."),
                admin.id,
                "grant-1",
            )
    await engine.dispose()


@pytest.mark.anyio
async def test_revoke_is_durable_and_effectiveness_is_derived_from_state_and_time() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        admin = User(phone="13600000073")
        user = User(phone="13600000074")
        session.add_all((admin, user))
        await session.flush()
        plan = MembershipPlan(code="weekend", name="Weekend", duration_days=7, entitlement_codes=["lounge"], status="published")
        session.add(plan)
        await session.flush()
        now = datetime.now(UTC)
        expired = UserMembership(
            user_id=user.id,
            plan_id=plan.id,
            valid_from=now - timedelta(days=2),
            valid_until=now - timedelta(days=1),
            granted_by=admin.id,
            idempotency_key="expired",
        )
        session.add(expired)
        await session.flush()
        assert effective_membership_status(expired, now) == "expired"
        membership = UserMembership(
            user_id=user.id,
            plan_id=plan.id,
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(days=1),
            granted_by=admin.id,
            idempotency_key="active",
        )
        session.add(membership)
        await session.commit()
        revoked = await MembershipService(session).revoke(membership.id, admin.id, "Account closure.")
        assert revoked.status == "revoked"
        assert revoked.revoked_by == admin.id
        assert revoked.revoked_at is not None
        assert revoked.revoke_reason == "Account closure."
        assert effective_membership_status(revoked, now) == "revoked"
        events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == membership.id))).all()
        assert len(events) == 1
        assert events[0].payload_json["status"] == "revoked"
        with pytest.raises(MembershipError, match="Only active"):
            await MembershipService(session).revoke(membership.id, admin.id, "Repeat revoke.")
    await engine.dispose()


@pytest.mark.anyio
async def test_membership_plan_state_transitions_are_safe() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        admin = User(id=str(uuid4()), phone="13600000075")
        session.add(admin)
        await session.flush()
        service = MembershipService(session)
        plan = await service.create_plan(
            MembershipPlanCreate(code="state-safe", name="State Safe", duration_days=1, entitlement_codes=["access"], price_amount="1.00", currency="CNY", generation_quota=0, assistant_quota=0),
            admin.id,
        )
        await service.publish_plan(plan.id, admin.id)
        with pytest.raises(MembershipError, match="Only draft"):
            await service.publish_plan(plan.id, admin.id)
        archived = await service.archive_plan(plan.id, admin.id)
        assert archived.purchasable is False
        with pytest.raises(MembershipError, match="already archived"):
            await service.archive_plan(plan.id, admin.id)
    await engine.dispose()
