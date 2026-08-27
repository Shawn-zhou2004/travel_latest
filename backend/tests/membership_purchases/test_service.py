import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.integrations.alipay.adapter import AlipayPrecreateRequest, AlipayPrecreateResponse, AlipayWapPaymentRequest, AlipayWapRedirect, TradeQueryResult, VerifiedAlipayCallback
from app.models.base import Base, utc_now
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.membership_purchases.models import AIQuotaPeriod, MembershipPaymentAttempt, MembershipPaymentCallbackEvent, MembershipPurchase
from app.modules.membership_purchases.service import MembershipPurchaseError, MembershipPurchaseService
from app.modules.memberships.models import MembershipPlan, UserEntitlement, UserMembership


class FakeAlipayAdapter:
    app_id = "membership-sandbox-app"

    def __init__(self, query_status: str = "WAIT_BUYER_PAY") -> None:
        self.query_status = query_status
        self.created: list[AlipayWapPaymentRequest] = []
        self.precreated: list[AlipayPrecreateRequest] = []

    async def create_wap_redirect(self, request: AlipayWapPaymentRequest) -> AlipayWapRedirect:
        self.created.append(request)
        return AlipayWapRedirect(f"https://sandbox.example.test/{request.out_trade_no}")

    async def create_precreate(self, request: AlipayPrecreateRequest) -> AlipayPrecreateResponse:
        self.precreated.append(request)
        return AlipayPrecreateResponse(f"alipay://qr/{request.out_trade_no}", "10000")

    async def verify_callback(self, payload: dict[str, str]) -> VerifiedAlipayCallback | None:
        if payload.get("sign") != "valid":
            return None
        return VerifiedAlipayCallback(payload["out_trade_no"], payload["trade_no"], payload["trade_status"], Decimal(payload["total_amount"]))

    async def query_trade(self, out_trade_no: str) -> TradeQueryResult:
        return TradeQueryResult(out_trade_no, "query-trade", self.query_status, Decimal("19.90"), "10000")


@pytest.fixture
def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(_create_tables(engine))
    yield factory
    asyncio.run(engine.dispose())


async def _create_tables(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _plan_and_user(factory: async_sessionmaker[AsyncSession], *, status: str = "published", purchasable: bool = True) -> tuple[User, MembershipPlan]:
    async with factory() as session:
        user = User(id=str(uuid.uuid4()), phone="13900000001")
        plan = MembershipPlan(code=f"ai-{uuid.uuid4().hex[:8]}", name="AI planning", duration_days=30, entitlement_codes=["ai_planning"], status=status, price_amount=Decimal("19.90"), currency="CNY", generation_quota=10, assistant_quota=300, purchasable=purchasable)
        session.add_all([user, plan])
        await session.commit()
        return user, plan


def test_purchase_uses_server_plan_snapshot_and_reuses_idempotency(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def scenario() -> None:
        user, plan = await _plan_and_user(session_factory)
        async with session_factory() as session:
            service = MembershipPurchaseService(session)
            first = await service.create_purchase(user.id, plan.id, "purchase-key")
            second = await service.create_purchase(user.id, plan.id, "purchase-key")
            assert second.id == first.id
            assert first.amount == Decimal("19.90")
            assert first.duration_days == 30
            assert first.generation_quota == 10
            assert first.assistant_quota == 300
            with pytest.raises(MembershipPurchaseError, match="Idempotency-Key"):
                await service.create_purchase(user.id, str(uuid.uuid4()), "purchase-key")
    asyncio.run(scenario())


@pytest.mark.parametrize(("status", "purchasable"), [("draft", True), ("published", False)])
def test_unpublished_or_unpurchasable_plan_is_rejected(session_factory: async_sessionmaker[AsyncSession], status: str, purchasable: bool) -> None:
    async def scenario() -> None:
        user, plan = await _plan_and_user(session_factory, status=status, purchasable=purchasable)
        async with session_factory() as session:
            with pytest.raises(MembershipPurchaseError, match="not available"):
                await MembershipPurchaseService(session).create_purchase(user.id, plan.id, "purchase-key")
    asyncio.run(scenario())


def test_payment_idempotency_and_single_active_payment(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def scenario() -> None:
        user, plan = await _plan_and_user(session_factory)
        adapter = FakeAlipayAdapter()
        async with session_factory() as session:
            service = MembershipPurchaseService(session, adapter)
            purchase = await service.create_purchase(user.id, plan.id, "purchase-key")
            first, url = await service.create_payment(purchase, "payment-key")
            second, repeated_url = await service.create_payment(first, "payment-key")
            assert second.payment_no == first.payment_no
            assert url == repeated_url
            assert len(adapter.created) == 2
            with pytest.raises(MembershipPurchaseError, match="active payment"):
                await service.create_payment(first, "other-payment-key")
    asyncio.run(scenario())


def test_qr_attempt_reuse_expiry_refresh_query_and_callback(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def scenario() -> None:
        user, plan = await _plan_and_user(session_factory)
        adapter = FakeAlipayAdapter()
        async with session_factory() as session:
            service = MembershipPurchaseService(session, adapter)
            purchase = await service.create_purchase(user.id, plan.id, "qr-purchase")
            first_purchase, first = await service.create_or_get_qr_attempt(purchase.id, user.id)
            _, repeated = await service.create_or_get_qr_attempt(purchase.id, user.id)
            assert repeated is not None and repeated.id == first.id
            assert len(adapter.precreated) == 1
            assert adapter.precreated[0].timeout_express == "10m"
            assert first.expires_at - first.created_at <= timedelta(minutes=10, seconds=1)
            first.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
            with pytest.raises(MembershipPurchaseError, match="refresh"):
                await service.create_or_get_qr_attempt(first_purchase.id, user.id)
            _, expired = await service.current_qr_attempt(first_purchase.id, user.id)
            assert expired is not None and expired.status == "expired"
            _, refreshed = await service.refresh_qr_attempt(first_purchase.id, user.id)
            assert refreshed.id != first.id
            assert len(adapter.precreated) == 2
            adapter.query_status = "TRADE_SUCCESS"
            settled, paid_attempt = await service.query_qr_payment(first_purchase.id, user.id)
            assert settled.authorization_status == "authorized"
            assert paid_attempt is not None and paid_attempt.status == "paid"
            duplicate = await service.handle_callback({"app_id": adapter.app_id, "out_trade_no": refreshed.payment_no, "trade_no": "query-trade", "trade_status": "TRADE_SUCCESS", "total_amount": "19.90", "sign": "valid"})
            assert duplicate.authorization_status == "authorized"
            assert len((await session.scalars(select(AIQuotaPeriod).where(AIQuotaPeriod.membership_purchase_id == purchase.id))).all()) == 1
            assert len((await session.scalars(select(MembershipPaymentAttempt))).all()) == 2
    asyncio.run(scenario())


def test_qr_query_wait_closed_and_paid_refresh_rules(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def scenario() -> None:
        user, plan = await _plan_and_user(session_factory)
        adapter = FakeAlipayAdapter("WAIT_BUYER_PAY")
        async with session_factory() as session:
            service = MembershipPurchaseService(session, adapter)
            purchase = await service.create_purchase(user.id, plan.id, "qr-query-purchase")
            _, attempt = await service.create_or_get_qr_attempt(purchase.id, user.id)
            waiting_purchase, waiting_attempt = await service.query_qr_payment(purchase.id, user.id)
            assert waiting_purchase.payment_status == "paying"
            assert waiting_attempt is not None and waiting_attempt.status == "pending"
            adapter.query_status = "TRADE_CLOSED"
            _, closed_attempt = await service.query_qr_payment(purchase.id, user.id)
            assert closed_attempt is not None and closed_attempt.status == "closed"
            _, refreshed = await service.refresh_qr_attempt(purchase.id, user.id)
            adapter.query_status = "TRADE_SUCCESS"
            paid_purchase, _ = await service.query_qr_payment(purchase.id, user.id)
            assert paid_purchase.authorization_status == "authorized"
            with pytest.raises(MembershipPurchaseError, match="already been paid"):
                await service.refresh_qr_attempt(purchase.id, user.id)
            with pytest.raises(MembershipPurchaseError):
                await service.handle_callback({"app_id": adapter.app_id, "out_trade_no": attempt.payment_no, "trade_no": "late-closed-trade", "trade_status": "TRADE_SUCCESS", "total_amount": "19.90", "sign": "valid"})
            assert refreshed.status == "paid"
    asyncio.run(scenario())


def test_valid_duplicate_callback_invalid_facts_query_recovery_and_authorization_retry(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def scenario() -> None:
        user, plan = await _plan_and_user(session_factory)
        adapter = FakeAlipayAdapter()
        async with session_factory() as session:
            service = MembershipPurchaseService(session, adapter)
            purchase = await service.create_purchase(user.id, plan.id, "purchase-key")
            purchase, _ = await service.create_payment(purchase, "payment-key")
            payload = {"app_id": adapter.app_id, "out_trade_no": purchase.payment_no or "", "trade_no": "trade-1", "trade_status": "TRADE_SUCCESS", "total_amount": "19.90", "sign": "valid"}
            settled = await service.handle_callback(payload)
            duplicate = await service.handle_callback(payload)
            assert duplicate.id == settled.id
            assert duplicate.authorization_status == "authorized"
            assert len((await session.scalars(select(AIQuotaPeriod))).all()) == 1
            assert len((await session.scalars(select(UserMembership))).all()) == 1
            assert len((await session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "membership.entitlement_updated"))).all()) == 1
            with pytest.raises(MembershipPurchaseError):
                await service._settle(VerifiedAlipayCallback(purchase.payment_no or "", "trade-other", "TRADE_SUCCESS", Decimal("18.90")))
            with pytest.raises(MembershipPurchaseError):
                await service.handle_callback({**payload, "trade_no": "bad-signature", "sign": "bad"})
            assert len((await session.scalars(select(MembershipPaymentCallbackEvent).where(MembershipPaymentCallbackEvent.verification_status == "rejected"))).all()) == 1

            recovered = await service.create_purchase(user.id, plan.id, "recovery-purchase")
            recovered, _ = await service.create_payment(recovered, "recovery-payment")
            adapter.query_status = "TRADE_SUCCESS"
            recovered = await service.query_purchase_payment(recovered)
            assert recovered.authorization_status == "authorized"

            retry = await service.create_purchase(user.id, plan.id, "retry-purchase")
            retry, _ = await service.create_payment(retry, "retry-payment")
            retry.payment_status = "paid"
            retry.status = "paid"
            await session.commit()
            retry_id = retry.id
            original_commit = session.commit
            calls = 0

            async def fail_once() -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    await session.rollback()
                    raise RuntimeError("simulated authorization failure")
                await original_commit()

            session.commit = fail_once  # type: ignore[method-assign]
            with pytest.raises(RuntimeError, match="simulated"):
                await service.authorize_paid_purchase(retry_id)
            session.commit = original_commit  # type: ignore[method-assign]
            authorized = await service.authorize_paid_purchase(retry_id)
            again = await service.authorize_paid_purchase(retry_id)
            assert again.valid_until == authorized.valid_until
            periods = (await session.scalars(select(AIQuotaPeriod).where(AIQuotaPeriod.membership_purchase_id == retry_id))).all()
            assert len(periods) == 1
    asyncio.run(scenario())


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def test_purchase_activates_immediately_and_pushes_back_queued_periods(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def scenario() -> None:
        user, plan = await _plan_and_user(session_factory)
        adapter = FakeAlipayAdapter()
        async with session_factory() as session:
            service = MembershipPurchaseService(session, adapter)

            async def pay_and_authorize(key: str) -> MembershipPurchase:
                purchase = await service.create_purchase(user.id, plan.id, key)
                purchase, _ = await service.create_payment(purchase, f"{key}-payment")
                payload = {"app_id": adapter.app_id, "out_trade_no": purchase.payment_no or "", "trade_no": f"trade-{key}", "trade_status": "TRADE_SUCCESS", "total_amount": "19.90", "sign": "valid"}
                return await service.handle_callback(payload)

            first = await pay_and_authorize("first")
            second = await pay_and_authorize("second")
            # A new purchase activates immediately: it overlaps the running period instead of queuing behind it.
            assert second.valid_from is not None and first.valid_until is not None
            assert second.valid_from < first.valid_until

            # Simulate a legacy queued period: a paid purchase whose membership starts in the future.
            queued = await service.create_purchase(user.id, plan.id, "queued")
            queued.payment_status = "paid"
            queued.status = "paid"
            await session.flush()
            queued_start = utc_now() + timedelta(days=30)
            queued_membership = UserMembership(
                user_id=user.id,
                plan_id=plan.id,
                valid_from=queued_start,
                valid_until=queued_start + timedelta(days=30),
                grant_source="membership_purchase",
                granted_by=user.id,
                idempotency_key=queued.id,
            )
            session.add(queued_membership)
            await session.flush()
            session.add(UserEntitlement(membership_id=queued_membership.id, user_id=user.id, entitlement_code="ai_planning", valid_from=queued_membership.valid_from, valid_until=queued_membership.valid_until))
            session.add(AIQuotaPeriod(user_id=user.id, source_type="membership_purchase", membership_purchase_id=queued.id, period_start=queued_membership.valid_from, period_end=queued_membership.valid_until, generation_limit=10, assistant_limit=300))
            await session.commit()

            immediate = await pay_and_authorize("immediate")
            assert immediate.valid_from is not None and immediate.valid_until is not None
            assert immediate.valid_from <= utc_now()
            # The queued period is pushed back to chain after the new purchase, preserving its length.
            shifted = (await session.scalars(select(UserMembership).where(UserMembership.idempotency_key == queued.id))).one()
            assert shifted.valid_from is not None and _utc(shifted.valid_from) == _utc(immediate.valid_until)
            assert shifted.valid_until is not None and _utc(shifted.valid_until) == _utc(immediate.valid_until) + timedelta(days=30)
            entitlement = (await session.scalars(select(UserEntitlement).where(UserEntitlement.membership_id == shifted.id))).one()
            assert entitlement.valid_from is not None and _utc(entitlement.valid_from) == _utc(immediate.valid_until)
            quota_period = (await session.scalars(select(AIQuotaPeriod).where(AIQuotaPeriod.membership_purchase_id == queued.id))).one()
            assert quota_period.period_start is not None and _utc(quota_period.period_start) == _utc(immediate.valid_until)
            assert quota_period.period_end is not None and _utc(quota_period.period_end) == _utc(immediate.valid_until) + timedelta(days=30)
            # Already-started periods keep their windows.
            first_membership = (await session.scalars(select(UserMembership).where(UserMembership.idempotency_key == first.id))).one()
            assert first_membership.valid_until is not None and _utc(first_membership.valid_until) == _utc(first.valid_until)
    asyncio.run(scenario())
