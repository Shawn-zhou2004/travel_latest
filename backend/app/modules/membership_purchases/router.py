from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.integrations.alipay.adapter import AlipayAdapter, get_alipay_adapter
from app.modules.auth.dependencies import CurrentAdmin, CurrentConsumer
from app.modules.admin.models import AdminAction
from app.modules.membership_purchases.models import MembershipPaymentAttempt, MembershipPurchase
from app.modules.membership_purchases.schemas import AdminMembershipPurchasePage, AdminMembershipPurchaseResponse, MembershipPaymentCreate, MembershipPaymentResponse, MembershipPurchaseCreate, MembershipPurchasePage, MembershipPurchaseResponse, MembershipQrPaymentResponse
from app.modules.membership_purchases.service import MembershipPurchaseError, MembershipPurchaseService


router = APIRouter(tags=["membership-purchases"])
Session = Annotated[AsyncSession, Depends(get_session)]


def provide_alipay_adapter() -> AlipayAdapter:
    from app.core.settings import Settings
    return get_alipay_adapter(Settings())


def membership_return_url(purchase_id: str) -> str:
    from app.core.settings import Settings

    return f"{Settings().alipay_return_base_url.rstrip('/')}/memberships/return/{purchase_id}"


def _error(error: MembershipPurchaseError) -> HTTPException:
    return HTTPException(error.status_code, detail={"code": error.code, "message": error.message})


def _response(purchase: MembershipPurchase) -> MembershipPurchaseResponse:
    return MembershipPurchaseResponse(id=purchase.id, membership_plan_id=purchase.membership_plan_id, plan_name=purchase.plan_name_snapshot, amount=purchase.amount, currency=purchase.currency, duration_days=purchase.duration_days, generation_quota=purchase.generation_quota, assistant_quota=purchase.assistant_quota, status=purchase.status, payment_status=purchase.payment_status, authorization_status=purchase.authorization_status, payment_no=purchase.payment_no, paid_at=purchase.paid_at, authorized_at=purchase.authorized_at, valid_from=purchase.valid_from, valid_until=purchase.valid_until, created_at=purchase.created_at)


def _qr_response(purchase: MembershipPurchase, attempt: MembershipPaymentAttempt | None, *, include_qr_code: bool = True) -> MembershipQrPaymentResponse:
    return MembershipQrPaymentResponse(
        attempt_id=attempt.id if attempt else None,
        payment_no=attempt.payment_no if attempt else None,
        qr_code=attempt.qr_code if include_qr_code and attempt and attempt.status in {"pending", "paying"} else None,
        expires_at=attempt.expires_at if attempt else None,
        status=attempt.status if attempt else None,
        payment_status=purchase.payment_status,
        authorization_status=purchase.authorization_status,
    )


def _admin_response(purchase: MembershipPurchase) -> AdminMembershipPurchaseResponse:
    return AdminMembershipPurchaseResponse(
        id=purchase.id,
        user_id=purchase.user_id,
        membership_plan_id=purchase.membership_plan_id,
        plan_name=purchase.plan_name_snapshot,
        amount=purchase.amount,
        currency=purchase.currency,
        duration_days=purchase.duration_days,
        generation_quota=purchase.generation_quota,
        assistant_quota=purchase.assistant_quota,
        status=purchase.status,
        payment_status=purchase.payment_status,
        authorization_status=purchase.authorization_status,
        failure_code="PAYMENT_FAILED" if purchase.payment_status == "failed" else "AUTHORIZATION_FAILED" if purchase.authorization_status == "failed" else None,
        paid_at=purchase.paid_at,
        authorized_at=purchase.authorized_at,
        valid_from=purchase.valid_from,
        valid_until=purchase.valid_until,
        created_at=purchase.created_at,
    )


def _require_platform_admin(claims: CurrentAdmin) -> None:
    if "platform_admin" not in claims.roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Platform admin role required."})


@router.post("/membership-purchases", response_model=MembershipPurchaseResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase(body: MembershipPurchaseCreate, claims: CurrentConsumer, session: Session, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]) -> MembershipPurchaseResponse:
    try:
        return _response(await MembershipPurchaseService(session).create_purchase(claims.user_id, body.membership_plan_id, idempotency_key))
    except MembershipPurchaseError as error:
        raise _error(error) from error


@router.post("/membership-purchases/{purchase_id}/payments", response_model=MembershipPaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(purchase_id: str, body: MembershipPaymentCreate, claims: CurrentConsumer, session: Session, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)], adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> MembershipPaymentResponse:
    purchase = await session.get(MembershipPurchase, purchase_id)
    if purchase is None or purchase.user_id != claims.user_id:
        raise HTTPException(404, detail={"code": "MEMBERSHIP_PURCHASE_NOT_FOUND", "message": "The membership purchase is unavailable."})
    try:
        purchase, redirect_url = await MembershipPurchaseService(session, adapter).create_payment(
            purchase, idempotency_key, return_url=membership_return_url(purchase.id)
        )
    except MembershipPurchaseError as error:
        raise _error(error) from error
    return MembershipPaymentResponse(payment_no=purchase.payment_no or "", amount=purchase.amount, currency=purchase.currency, status=purchase.payment_status, redirect_url=redirect_url)


@router.post("/membership-purchases/{purchase_id}:query-payment", response_model=MembershipPurchaseResponse | MembershipQrPaymentResponse)
async def query_payment(purchase_id: str, claims: CurrentConsumer, session: Session, adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> MembershipPurchaseResponse | MembershipQrPaymentResponse:
    purchase = await session.get(MembershipPurchase, purchase_id)
    if purchase is None or purchase.user_id != claims.user_id:
        raise HTTPException(404, detail={"code": "MEMBERSHIP_PURCHASE_NOT_FOUND", "message": "The membership purchase is unavailable."})
    try:
        if purchase.current_payment_attempt_id is not None:
            purchase, attempt = await MembershipPurchaseService(session, adapter).query_qr_payment(purchase_id, claims.user_id)
            return _qr_response(purchase, attempt, include_qr_code=False)
        return _response(await MembershipPurchaseService(session, adapter).query_purchase_payment(purchase))
    except MembershipPurchaseError as error:
        raise _error(error) from error


@router.post("/membership-purchases/{purchase_id}/qr-payments", response_model=MembershipQrPaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_qr_payment(purchase_id: str, claims: CurrentConsumer, session: Session, adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> MembershipQrPaymentResponse:
    try:
        purchase, attempt = await MembershipPurchaseService(session, adapter).create_or_get_qr_attempt(purchase_id, claims.user_id)
        return _qr_response(purchase, attempt)
    except MembershipPurchaseError as error:
        raise _error(error) from error


@router.get("/membership-purchases/{purchase_id}/qr-payments/current", response_model=MembershipQrPaymentResponse)
async def current_qr_payment(purchase_id: str, claims: CurrentConsumer, session: Session) -> MembershipQrPaymentResponse:
    try:
        purchase, attempt = await MembershipPurchaseService(session).current_qr_attempt(purchase_id, claims.user_id)
        return _qr_response(purchase, attempt)
    except MembershipPurchaseError as error:
        raise _error(error) from error


@router.post("/membership-purchases/{purchase_id}/qr-payments:refresh", response_model=MembershipQrPaymentResponse)
async def refresh_qr_payment(purchase_id: str, claims: CurrentConsumer, session: Session, adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> MembershipQrPaymentResponse:
    try:
        purchase, attempt = await MembershipPurchaseService(session, adapter).refresh_qr_attempt(purchase_id, claims.user_id)
        return _qr_response(purchase, attempt)
    except MembershipPurchaseError as error:
        raise _error(error) from error


@router.get("/membership-purchases/mine", response_model=MembershipPurchasePage)
async def list_my_purchases(claims: CurrentConsumer, session: Session) -> MembershipPurchasePage:
    purchases = (await session.scalars(select(MembershipPurchase).where(MembershipPurchase.user_id == claims.user_id).order_by(MembershipPurchase.created_at.desc()))).all()
    return MembershipPurchasePage(items=[_response(purchase) for purchase in purchases])


@router.get("/admin/membership-purchases", response_model=AdminMembershipPurchasePage)
async def list_admin_purchases(
    claims: CurrentAdmin,
    session: Session,
    status_filter: str | None = Query(default=None, alias="status"),
) -> AdminMembershipPurchasePage:
    _require_platform_admin(claims)
    statement = select(MembershipPurchase).order_by(MembershipPurchase.created_at.desc())
    if status_filter is not None:
        if status_filter not in {"pending_payment", "paid", "closed"}:
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Unsupported membership purchase status."})
        statement = statement.where(MembershipPurchase.status == status_filter)
    purchases = (await session.scalars(statement)).all()
    return AdminMembershipPurchasePage(items=[_admin_response(purchase) for purchase in purchases])


@router.post("/admin/membership-purchases/{purchase_id}:retry-authorization", response_model=AdminMembershipPurchaseResponse)
async def retry_purchase_authorization(purchase_id: str, claims: CurrentAdmin, session: Session) -> AdminMembershipPurchaseResponse:
    _require_platform_admin(claims)
    purchase = await session.get(MembershipPurchase, purchase_id)
    if purchase is None:
        raise HTTPException(404, detail={"code": "MEMBERSHIP_PURCHASE_NOT_FOUND", "message": "The membership purchase is unavailable."})
    if purchase.payment_status != "paid" or purchase.authorization_status == "authorized":
        raise HTTPException(409, detail={"code": "AUTHORIZATION_RETRY_NOT_ALLOWED", "message": "Only paid purchases awaiting authorization can be retried."})
    try:
        purchase = await MembershipPurchaseService(session).authorize_paid_purchase(purchase.id)
    except MembershipPurchaseError as error:
        raise _error(error) from error
    session.add(AdminAction(
        actor_id=claims.user_id,
        action="membership_purchase.authorization_retried",
        target_type="membership_purchase",
        target_id=purchase.id,
        reason="Retried paid membership purchase authorization.",
        result_json={"authorization_status": purchase.authorization_status},
    ))
    await session.commit()
    return _admin_response(purchase)


@router.post("/membership-payments/alipay/callback", response_class=PlainTextResponse)
async def alipay_callback(request: Request, session: Session, adapter: Annotated[AlipayAdapter, Depends(provide_alipay_adapter)]) -> PlainTextResponse:
    raw_body = await request.body()
    if len(raw_body) > 16_384:
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    try:
        pairs = parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=32)
    except (UnicodeDecodeError, ValueError):
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    if len({key for key, _ in pairs}) != len(pairs):
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    try:
        await MembershipPurchaseService(session, adapter).handle_callback(dict(pairs))
    except MembershipPurchaseError:
        return PlainTextResponse("failure", status_code=status.HTTP_400_BAD_REQUEST)
    return PlainTextResponse("success")
