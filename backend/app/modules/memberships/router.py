from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.dependencies import CurrentAdmin, CurrentConsumer
from app.modules.memberships.models import MembershipPlan, UserEntitlement, UserMembership
from app.modules.memberships.schemas import (
    AdminMembershipResponse,
    EntitlementResponse,
    MembershipGrantCreate,
    MembershipPlanCreate,
    MembershipPlanPage,
    MembershipPlanResponse,
    MembershipPlanUpdate,
    MembershipResponse,
    MembershipRevokeCreate,
)
from app.modules.memberships.service import MembershipError, MembershipService, effective_membership_status


router = APIRouter(tags=["memberships"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _now() -> datetime:
    return datetime.now(UTC)


def _error(error: MembershipError) -> HTTPException:
    return HTTPException(error.status_code, detail={"code": error.code, "message": error.message})


def _require_platform_admin(claims: CurrentAdmin) -> None:
    if "platform_admin" not in claims.roles:
        raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Platform admin role required."})


def _plan_response(plan: MembershipPlan) -> MembershipPlanResponse:
    return MembershipPlanResponse(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        duration_days=plan.duration_days,
        entitlement_codes=list(plan.entitlement_codes),
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        price_amount=plan.price_amount,
        currency=plan.currency,
        generation_quota=plan.generation_quota,
        assistant_quota=plan.assistant_quota,
        purchasable=plan.purchasable,
    )


async def _membership_response(session: AsyncSession, membership: UserMembership, *, admin: bool = False) -> MembershipResponse | AdminMembershipResponse:
    plan = await session.get(MembershipPlan, membership.plan_id)
    if plan is None:
        raise HTTPException(404, detail={"code": "MEMBERSHIP_NOT_FOUND", "message": "The membership is unavailable."})
    values = {
        "id": membership.id,
        "plan_id": plan.id,
        "plan_code": plan.code,
        "plan_name": plan.name,
        "status": effective_membership_status(membership),
        "valid_from": membership.valid_from,
        "valid_until": membership.valid_until,
        "entitlement_codes": list(plan.entitlement_codes),
    }
    if not admin:
        return MembershipResponse(**values)
    return AdminMembershipResponse(
        **values,
        user_id=membership.user_id,
        grant_source=membership.grant_source,
        granted_by=membership.granted_by,
        revoked_by=membership.revoked_by,
        revoked_at=membership.revoked_at,
        revoke_reason=membership.revoke_reason,
    )


@router.get("/membership-plans", response_model=list[MembershipPlanResponse])
async def list_published_membership_plans(session: Session) -> list[MembershipPlanResponse]:
    plans = (await session.scalars(
        select(MembershipPlan).where(MembershipPlan.status == "published").order_by(MembershipPlan.created_at.desc())
    )).all()
    return [_plan_response(plan) for plan in plans]


@router.get("/users/me/entitlements", response_model=list[EntitlementResponse])
async def list_my_effective_entitlements(claims: CurrentConsumer, session: Session) -> list[EntitlementResponse]:
    now = _now()
    entitlements = (await session.scalars(
        select(UserEntitlement)
        .join(UserMembership, UserMembership.id == UserEntitlement.membership_id)
        .where(
            UserEntitlement.user_id == claims.user_id,
            UserEntitlement.valid_from <= now,
            UserEntitlement.valid_until > now,
            UserMembership.status == "active",
            UserMembership.valid_from <= now,
            UserMembership.valid_until > now,
        )
        .order_by(UserEntitlement.entitlement_code)
    )).all()
    return [EntitlementResponse(
        id=item.id,
        membership_id=item.membership_id,
        code=item.entitlement_code,
        valid_from=item.valid_from,
        valid_until=item.valid_until,
    ) for item in entitlements]


@router.get("/memberships/{membership_id}", response_model=MembershipResponse)
async def get_my_membership(membership_id: str, claims: CurrentConsumer, session: Session) -> MembershipResponse:
    membership = await session.get(UserMembership, membership_id)
    if membership is None or membership.user_id != claims.user_id:
        raise HTTPException(404, detail={"code": "MEMBERSHIP_NOT_FOUND", "message": "The membership is unavailable."})
    response = await _membership_response(session, membership)
    assert isinstance(response, MembershipResponse)
    return response


@router.get("/admin/membership-plans", response_model=MembershipPlanPage)
async def list_membership_plans(claims: CurrentAdmin, session: Session, status_filter: str | None = Query(default=None, alias="status")) -> MembershipPlanPage:
    _require_platform_admin(claims)
    statement = select(MembershipPlan).order_by(MembershipPlan.updated_at.desc())
    if status_filter is not None:
        if status_filter not in {"draft", "published", "archived"}:
            raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Unsupported membership plan status."})
        statement = statement.where(MembershipPlan.status == status_filter)
    plans = (await session.scalars(statement)).all()
    return MembershipPlanPage(items=[_plan_response(plan) for plan in plans])


@router.post("/admin/membership-plans", response_model=MembershipPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_membership_plan(body: MembershipPlanCreate, claims: CurrentAdmin, session: Session) -> MembershipPlanResponse:
    _require_platform_admin(claims)
    try:
        plan = await MembershipService(session).create_plan(body, claims.user_id)
    except MembershipError as error:
        raise _error(error) from error
    return _plan_response(plan)


@router.patch("/admin/membership-plans/{plan_id}", response_model=MembershipPlanResponse)
async def update_membership_plan(plan_id: str, body: MembershipPlanUpdate, claims: CurrentAdmin, session: Session) -> MembershipPlanResponse:
    _require_platform_admin(claims)
    try:
        plan = await MembershipService(session).update_plan(plan_id, body, claims.user_id)
    except MembershipError as error:
        raise _error(error) from error
    return _plan_response(plan)


@router.post("/admin/membership-plans/{plan_id}:publish", response_model=MembershipPlanResponse)
async def publish_membership_plan(plan_id: str, claims: CurrentAdmin, session: Session) -> MembershipPlanResponse:
    _require_platform_admin(claims)
    try:
        plan = await MembershipService(session).publish_plan(plan_id, claims.user_id)
    except MembershipError as error:
        raise _error(error) from error
    return _plan_response(plan)


@router.post("/admin/membership-plans/{plan_id}:archive", response_model=MembershipPlanResponse)
async def archive_membership_plan(plan_id: str, claims: CurrentAdmin, session: Session) -> MembershipPlanResponse:
    _require_platform_admin(claims)
    try:
        plan = await MembershipService(session).archive_plan(plan_id, claims.user_id)
    except MembershipError as error:
        raise _error(error) from error
    return _plan_response(plan)


@router.post("/admin/memberships", response_model=AdminMembershipResponse, status_code=status.HTTP_201_CREATED)
async def grant_membership(
    body: MembershipGrantCreate,
    claims: CurrentAdmin,
    session: Session,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> AdminMembershipResponse:
    _require_platform_admin(claims)
    try:
        membership = await MembershipService(session).grant(body, claims.user_id, idempotency_key)
    except MembershipError as error:
        raise _error(error) from error
    response = await _membership_response(session, membership, admin=True)
    assert isinstance(response, AdminMembershipResponse)
    return response


@router.post("/admin/memberships/{membership_id}:revoke", response_model=AdminMembershipResponse)
async def revoke_membership(membership_id: str, body: MembershipRevokeCreate, claims: CurrentAdmin, session: Session) -> AdminMembershipResponse:
    _require_platform_admin(claims)
    try:
        membership = await MembershipService(session).revoke(membership_id, claims.user_id, body.reason)
    except MembershipError as error:
        raise _error(error) from error
    response = await _membership_response(session, membership, admin=True)
    assert isinstance(response, AdminMembershipResponse)
    return response
