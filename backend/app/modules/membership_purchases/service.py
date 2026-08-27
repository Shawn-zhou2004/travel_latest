from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.alipay.adapter import (
    AlipayAdapter,
    AlipayPrecreateRequest,
    AlipayWapPaymentRequest,
    TradeQueryResult,
    UnavailableAlipayAdapter,
    VerifiedAlipayCallback,
)
from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.membership_purchases.models import AIQuotaPeriod, MembershipPaymentAttempt, MembershipPaymentCallbackEvent, MembershipPurchase
from app.modules.memberships.models import MembershipPlan, UserEntitlement, UserMembership


class MembershipPurchaseError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code


class MembershipPurchaseService:
    def __init__(self, session: AsyncSession, adapter: AlipayAdapter | None = None) -> None:
        self.session = session
        self.adapter = adapter

    @staticmethod
    def payment_no_for(purchase_id: str, idempotency_key: str) -> str:
        return f"MP{sha256(f'{purchase_id}:{idempotency_key}'.encode()).hexdigest()[:32].upper()}"

    @staticmethod
    def qr_payment_no_for(purchase_id: str, attempt_id: str) -> str:
        return f"MQ{sha256(f'{purchase_id}:{attempt_id}'.encode()).hexdigest()[:32].upper()}"

    def _require_adapter(self) -> AlipayAdapter:
        if self.adapter is None or isinstance(self.adapter, UnavailableAlipayAdapter):
            raise MembershipPurchaseError("PAYMENT_NOT_CONFIGURED", "Alipay is not configured.", 503)
        return self.adapter

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    async def create_purchase(self, user_id: str, membership_plan_id: str, idempotency_key: str) -> MembershipPurchase:
        existing = await self.session.scalar(select(MembershipPurchase).where(
            MembershipPurchase.user_id == user_id,
            MembershipPurchase.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            if existing.membership_plan_id != membership_plan_id:
                raise MembershipPurchaseError("IDEMPOTENCY_CONFLICT", "Idempotency-Key is already bound to another membership plan.")
            return existing
        plan = await self.session.scalar(select(MembershipPlan).where(MembershipPlan.id == membership_plan_id).with_for_update())
        if plan is None:
            raise MembershipPurchaseError("MEMBERSHIP_PLAN_NOT_FOUND", "The membership plan is unavailable.", 404)
        if plan.status != "published" or not plan.purchasable:
            raise MembershipPurchaseError("MEMBERSHIP_PLAN_NOT_PURCHASABLE", "The membership plan is not available for purchase.")
        if plan.currency != "CNY" or plan.price_amount <= Decimal("0.00"):
            raise MembershipPurchaseError("MEMBERSHIP_PLAN_INVALID", "The membership plan cannot be paid with Alipay.")
        purchase = MembershipPurchase(
            user_id=user_id,
            membership_plan_id=plan.id,
            plan_name_snapshot=plan.name,
            amount=plan.price_amount,
            currency=plan.currency,
            duration_days=plan.duration_days,
            generation_quota=plan.generation_quota,
            assistant_quota=plan.assistant_quota,
            idempotency_key=idempotency_key,
        )
        self.session.add(purchase)
        await self.session.commit()
        return purchase

    async def create_payment(self, purchase: MembershipPurchase, idempotency_key: str, *, return_url: str | None = None) -> tuple[MembershipPurchase, str]:
        adapter = self._require_adapter()
        purchase = await self.session.scalar(select(MembershipPurchase).where(MembershipPurchase.id == purchase.id).with_for_update())
        if purchase is None:
            raise MembershipPurchaseError("MEMBERSHIP_PURCHASE_NOT_FOUND", "The membership purchase is unavailable.", 404)
        if purchase.status != "pending_payment" or purchase.payment_status not in {"pending", "paying"}:
            raise MembershipPurchaseError("PAYMENT_NOT_ALLOWED", "A payment cannot be created for this purchase.")
        if purchase.currency != "CNY":
            raise MembershipPurchaseError("PAYMENT_NOT_ALLOWED", "Alipay payments require CNY.")
        expected_payment_no = self.payment_no_for(purchase.id, idempotency_key)
        if purchase.payment_no is not None and purchase.payment_no != expected_payment_no:
            raise MembershipPurchaseError("PAYMENT_IN_PROGRESS", "An active payment already exists for this purchase.")
        if purchase.payment_no is None:
            purchase.payment_no = expected_payment_no
            purchase.payment_status = "paying"
            await self.session.commit()
        try:
            redirect = await adapter.create_wap_redirect(AlipayWapPaymentRequest(
                out_trade_no=purchase.payment_no,
                total_amount=purchase.amount,
                subject=purchase.plan_name_snapshot,
                return_url=return_url,
            ))
        except Exception as error:
            raise MembershipPurchaseError("PAYMENT_PROVIDER_UNAVAILABLE", "Alipay checkout is temporarily unavailable.", 503) from error
        if not redirect.url.startswith(("https://", "http://")):
            raise MembershipPurchaseError("PAYMENT_PROVIDER_INVALID_RESPONSE", "Alipay returned an invalid checkout response.", 503)
        return purchase, redirect.url

    async def _locked_purchase_for_owner(self, purchase_id: str, user_id: str) -> MembershipPurchase:
        purchase = await self.session.scalar(select(MembershipPurchase).where(
            MembershipPurchase.id == purchase_id,
            MembershipPurchase.user_id == user_id,
        ).with_for_update())
        if purchase is None:
            raise MembershipPurchaseError("MEMBERSHIP_PURCHASE_NOT_FOUND", "The membership purchase is unavailable.", 404)
        return purchase

    async def _current_attempt(self, purchase: MembershipPurchase) -> MembershipPaymentAttempt | None:
        if purchase.current_payment_attempt_id is None:
            return None
        return await self.session.scalar(select(MembershipPaymentAttempt).where(
            MembershipPaymentAttempt.id == purchase.current_payment_attempt_id
        ).with_for_update())

    async def _expire_current_attempt(self, purchase: MembershipPurchase, now: datetime) -> MembershipPaymentAttempt | None:
        attempt = await self._current_attempt(purchase)
        if attempt is not None and attempt.status in {"pending", "paying"} and self._as_utc(attempt.expires_at) <= now:
            attempt.status = "expired"
            await self.session.flush()
        return attempt

    async def _create_qr_attempt(self, purchase: MembershipPurchase, now: datetime) -> MembershipPaymentAttempt:
        adapter = self._require_adapter()
        if purchase.status != "pending_payment" or purchase.payment_status not in {"pending", "paying"} or purchase.currency != "CNY":
            raise MembershipPurchaseError("PAYMENT_NOT_ALLOWED", "A payment cannot be created for this purchase.")
        attempt_id = new_uuid()
        attempt = MembershipPaymentAttempt(
            id=attempt_id,
            membership_purchase_id=purchase.id,
            payment_no=self.qr_payment_no_for(purchase.id, attempt_id),
            provider="alipay_sandbox",
            amount=purchase.amount,
            currency=purchase.currency,
            expires_at=now,
        )
        self.session.add(attempt)
        await self.session.flush()
        try:
            response = await adapter.create_precreate(AlipayPrecreateRequest(
                out_trade_no=attempt.payment_no,
                total_amount=attempt.amount,
                subject=purchase.plan_name_snapshot,
                timeout_express="10m",
            ))
        except Exception as error:
            await self.session.rollback()
            raise MembershipPurchaseError("PAYMENT_PROVIDER_UNAVAILABLE", "Alipay checkout is temporarily unavailable.", 503) from error
        if not response.qr_code:
            await self.session.rollback()
            raise MembershipPurchaseError("PAYMENT_PROVIDER_INVALID_RESPONSE", "Alipay returned an invalid QR payment response.", 503)
        attempt.qr_code = response.qr_code
        attempt.expires_at = utc_now() + timedelta(minutes=10)
        purchase.current_payment_attempt_id = attempt.id
        purchase.payment_status = "paying"
        await self.session.commit()
        return attempt

    async def create_or_get_qr_attempt(self, purchase_id: str, user_id: str) -> tuple[MembershipPurchase, MembershipPaymentAttempt | None]:
        purchase = await self._locked_purchase_for_owner(purchase_id, user_id)
        if purchase.authorization_status == "authorized" or purchase.payment_status == "paid":
            raise MembershipPurchaseError("PAYMENT_NOT_ALLOWED", "The membership purchase has already been paid.")
        now = utc_now()
        attempt = await self._expire_current_attempt(purchase, now)
        if attempt is not None and attempt.status in {"pending", "paying"} and self._as_utc(attempt.expires_at) > now:
            await self.session.commit()
            return purchase, attempt
        if attempt is not None:
            raise MembershipPurchaseError("QR_PAYMENT_REFRESH_REQUIRED", "The QR payment has expired or closed; refresh it manually.")
        return purchase, await self._create_qr_attempt(purchase, now)

    async def current_qr_attempt(self, purchase_id: str, user_id: str) -> tuple[MembershipPurchase, MembershipPaymentAttempt | None]:
        purchase = await self._locked_purchase_for_owner(purchase_id, user_id)
        attempt = await self._expire_current_attempt(purchase, utc_now())
        await self.session.commit()
        return purchase, attempt

    async def refresh_qr_attempt(self, purchase_id: str, user_id: str) -> tuple[MembershipPurchase, MembershipPaymentAttempt]:
        purchase = await self._locked_purchase_for_owner(purchase_id, user_id)
        if purchase.authorization_status == "authorized" or purchase.payment_status == "paid":
            raise MembershipPurchaseError("PAYMENT_NOT_ALLOWED", "The membership purchase has already been paid.")
        now = utc_now()
        attempt = await self._expire_current_attempt(purchase, now)
        if attempt is None or attempt.status not in {"expired", "closed"}:
            raise MembershipPurchaseError("QR_PAYMENT_REFRESH_NOT_ALLOWED", "Only an expired or closed QR payment can be refreshed.")
        return purchase, await self._create_qr_attempt(purchase, now)

    @staticmethod
    def _facts(callback: VerifiedAlipayCallback) -> dict[str, object]:
        return {"out_trade_no": callback.out_trade_no, "trade_no": callback.trade_no, "trade_status": callback.trade_status, "total_amount": str(callback.total_amount)}

    async def _record_rejected_callback(self, payload: Mapping[str, str]) -> None:
        facts = {key: payload[key] for key in ("app_id", "out_trade_no", "trade_no", "trade_status", "total_amount") if payload.get(key)}
        self.session.add(MembershipPaymentCallbackEvent(provider="alipay_sandbox", raw_payload=facts, verification_status="rejected", verification_error="callback_verification_failed", processing_status="failed", processing_error="callback_verification_failed"))
        await self.session.commit()

    async def _record_verified_callback_failure(self, callback: VerifiedAlipayCallback) -> None:
        existing = await self.session.scalar(select(MembershipPaymentCallbackEvent).where(
            MembershipPaymentCallbackEvent.provider == "alipay_sandbox",
            MembershipPaymentCallbackEvent.provider_transaction_id == callback.trade_no,
        ))
        if existing is None:
            self.session.add(MembershipPaymentCallbackEvent(
                provider="alipay_sandbox",
                provider_transaction_id=callback.trade_no,
                raw_payload=self._facts(callback),
                verification_status="verified",
                verified_at=utc_now(),
                processing_status="failed",
                processing_error="callback_facts_invalid",
            ))
            await self.session.commit()

    async def _settle(self, callback: VerifiedAlipayCallback, *, callback_app_id: str | None = None, require_callback_app_id: bool = False) -> MembershipPurchase:
        adapter = self._require_adapter()
        if (callback.trade_status not in {"TRADE_SUCCESS", "TRADE_FINISHED"} or not callback.out_trade_no or not callback.trade_no or callback.total_amount <= 0 or (require_callback_app_id and callback_app_id != getattr(adapter, "app_id", None))):
            raise MembershipPurchaseError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        attempt = await self.session.scalar(select(MembershipPaymentAttempt).where(
            MembershipPaymentAttempt.payment_no == callback.out_trade_no
        ).with_for_update())
        purchase = None
        if attempt is not None:
            purchase = await self.session.scalar(select(MembershipPurchase).where(
                MembershipPurchase.id == attempt.membership_purchase_id
            ).with_for_update())
            if purchase is None or attempt.amount != callback.total_amount or attempt.currency != "CNY" or attempt.status in {"expired", "closed", "failed"}:
                raise MembershipPurchaseError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
            if attempt.provider_transaction_id and attempt.provider_transaction_id != callback.trade_no:
                raise MembershipPurchaseError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        else:
            purchase = await self.session.scalar(select(MembershipPurchase).where(MembershipPurchase.payment_no == callback.out_trade_no).with_for_update())
        if purchase is None or purchase.amount != callback.total_amount or purchase.currency != "CNY":
            raise MembershipPurchaseError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        if purchase.provider_transaction_id and purchase.provider_transaction_id != callback.trade_no:
            raise MembershipPurchaseError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        event = await self.session.scalar(select(MembershipPaymentCallbackEvent).where(
            MembershipPaymentCallbackEvent.provider == "alipay_sandbox",
            MembershipPaymentCallbackEvent.provider_transaction_id == callback.trade_no,
        ))
        if event is None:
            event = MembershipPaymentCallbackEvent(provider="alipay_sandbox", provider_transaction_id=callback.trade_no, membership_purchase_id=purchase.id, raw_payload=self._facts(callback), verification_status="verified", verified_at=utc_now())
            self.session.add(event)
        elif event.membership_purchase_id != purchase.id:
            raise MembershipPurchaseError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        if purchase.payment_status != "paid":
            purchase.payment_status = "paid"
            purchase.status = "paid"
            purchase.provider_transaction_id = callback.trade_no
            purchase.paid_at = utc_now()
        if attempt is not None and attempt.status != "paid":
            attempt.status = "paid"
            attempt.provider_transaction_id = callback.trade_no
            attempt.paid_at = utc_now()
        event.processing_status = "processed"
        event.processing_error = None
        event.processed_at = utc_now()
        await self.session.commit()
        return await self.authorize_paid_purchase(purchase.id)

    async def handle_callback(self, payload: Mapping[str, str]) -> MembershipPurchase:
        adapter = self._require_adapter()
        try:
            verified = await adapter.verify_callback(payload)
        except Exception:
            verified = None
        if verified is None:
            await self._record_rejected_callback(payload)
            raise MembershipPurchaseError("PAYMENT_CALLBACK_INVALID", "Payment callback was rejected.", 400)
        try:
            return await self._settle(verified, callback_app_id=payload.get("app_id"), require_callback_app_id=True)
        except MembershipPurchaseError:
            await self._record_verified_callback_failure(verified)
            raise

    async def query_purchase_payment(self, purchase: MembershipPurchase) -> MembershipPurchase:
        if purchase.payment_status == "paid":
            return await self.authorize_paid_purchase(purchase.id)
        if purchase.payment_no is None or purchase.payment_status == "failed":
            return purchase
        adapter = self._require_adapter()
        try:
            result = await adapter.query_trade(purchase.payment_no)
        except Exception as error:
            raise MembershipPurchaseError("PAYMENT_PROVIDER_UNAVAILABLE", "Alipay payment query is temporarily unavailable.", 503) from error
        if not isinstance(result, TradeQueryResult):
            raise MembershipPurchaseError("PAYMENT_PROVIDER_INVALID_RESPONSE", "Alipay returned an invalid payment response.", 503)
        if result.gateway_code == "10000" and result.trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"} and result.out_trade_no == purchase.payment_no and result.trade_no and result.total_amount is not None:
            return await self._settle(VerifiedAlipayCallback(result.out_trade_no, result.trade_no, result.trade_status, result.total_amount))
        return purchase

    async def query_qr_payment(self, purchase_id: str, user_id: str) -> tuple[MembershipPurchase, MembershipPaymentAttempt | None]:
        purchase = await self._locked_purchase_for_owner(purchase_id, user_id)
        if purchase.payment_status == "paid":
            return await self.authorize_paid_purchase(purchase.id), await self._current_attempt(purchase)
        attempt = await self._expire_current_attempt(purchase, utc_now())
        if attempt is None or attempt.status not in {"pending", "paying"}:
            await self.session.commit()
            return purchase, attempt
        adapter = self._require_adapter()
        try:
            result = await adapter.query_trade(attempt.payment_no)
        except Exception as error:
            raise MembershipPurchaseError("PAYMENT_PROVIDER_UNAVAILABLE", "Alipay payment query is temporarily unavailable.", 503) from error
        if not isinstance(result, TradeQueryResult):
            raise MembershipPurchaseError("PAYMENT_PROVIDER_INVALID_RESPONSE", "Alipay returned an invalid payment response.", 503)
        if result.gateway_code == "10000" and result.trade_status in {"TRADE_SUCCESS", "TRADE_FINISHED"} and result.out_trade_no == attempt.payment_no and result.trade_no and result.total_amount is not None:
            purchase = await self._settle(VerifiedAlipayCallback(result.out_trade_no, result.trade_no, result.trade_status, result.total_amount))
            attempt = await self._current_attempt(purchase)
        elif result.gateway_code == "10000" and result.trade_status == "TRADE_CLOSED":
            attempt.status = "closed"
            await self.session.commit()
        return purchase, attempt

    async def authorize_paid_purchase(self, purchase_id: str) -> MembershipPurchase:
        purchase = await self.session.scalar(select(MembershipPurchase).where(MembershipPurchase.id == purchase_id).with_for_update())
        if purchase is None:
            raise MembershipPurchaseError("MEMBERSHIP_PURCHASE_NOT_FOUND", "The membership purchase is unavailable.", 404)
        if purchase.payment_status != "paid":
            raise MembershipPurchaseError("PURCHASE_NOT_PAID", "The membership purchase has not been paid.")
        if purchase.authorization_status == "authorized":
            return purchase
        # Locking the user row serializes concurrent authorizations for the same user.
        await self.session.scalar(select(User.id).where(User.id == purchase.user_id).with_for_update())
        now = utc_now()
        # A paid purchase activates immediately instead of queuing behind active memberships.
        valid_from = now
        valid_until = valid_from + timedelta(days=purchase.duration_days)
        membership = UserMembership(
            user_id=purchase.user_id,
            plan_id=purchase.membership_plan_id,
            valid_from=valid_from,
            valid_until=valid_until,
            grant_source="membership_purchase",
            granted_by=purchase.user_id,
            idempotency_key=purchase.id,
        )
        plan = await self.session.get(MembershipPlan, purchase.membership_plan_id)
        if plan is None:
            raise MembershipPurchaseError("MEMBERSHIP_PLAN_NOT_FOUND", "The membership plan is unavailable.", 404)
        self.session.add(membership)
        await self.session.flush()
        self.session.add_all(UserEntitlement(membership_id=membership.id, user_id=purchase.user_id, entitlement_code=code, valid_from=valid_from, valid_until=valid_until) for code in plan.entitlement_codes)
        self.session.add(AIQuotaPeriod(user_id=purchase.user_id, source_type="membership_purchase", membership_purchase_id=purchase.id, period_start=valid_from, period_end=valid_until, generation_limit=purchase.generation_quota, assistant_limit=purchase.assistant_quota))
        # Shift queued future periods back so already-paid time is preserved without overlap.
        await self._push_back_future_memberships(purchase.user_id, valid_until, now)
        purchase.authorization_status = "authorized"
        purchase.authorized_at = now
        purchase.valid_from = valid_from
        purchase.valid_until = valid_until
        self.session.add(OutboxEvent(event_type="membership.entitlement_updated", aggregate_type="membership_purchase", aggregate_id=purchase.id, trace_id=new_uuid(), payload_json={"user_id": purchase.user_id, "membership_purchase_id": purchase.id, "valid_until": valid_until.isoformat()}))
        await self.session.commit()
        return purchase

    async def _push_back_future_memberships(self, user_id: str, chain_start: datetime, now: datetime) -> None:
        """Shift not-yet-started memberships (with entitlement and quota windows) to chain after a new purchase."""
        future = (await self.session.scalars(
            select(UserMembership).where(
                UserMembership.user_id == user_id,
                UserMembership.status == "active",
                UserMembership.valid_from > now,
            ).order_by(UserMembership.valid_from.asc())
        )).all()
        cursor = chain_start
        for membership in future:
            original_start = self._as_utc(membership.valid_from)
            original_until = self._as_utc(membership.valid_until)
            length = original_until - original_start
            shift = cursor - original_start
            if shift > timedelta(0):
                membership.valid_from = cursor
                membership.valid_until = cursor + length
                entitlements = (await self.session.scalars(
                    select(UserEntitlement).where(UserEntitlement.membership_id == membership.id)
                )).all()
                for entitlement in entitlements:
                    entitlement.valid_from = self._as_utc(entitlement.valid_from) + shift
                    entitlement.valid_until = self._as_utc(entitlement.valid_until) + shift
                quota_period = await self.session.scalar(
                    select(AIQuotaPeriod).where(AIQuotaPeriod.membership_purchase_id == membership.idempotency_key)
                )
                if quota_period is not None:
                    quota_period.period_start = self._as_utc(quota_period.period_start) + shift
                    quota_period.period_end = self._as_utc(quota_period.period_end) + shift
                cursor = membership.valid_until
            else:
                cursor = original_until
