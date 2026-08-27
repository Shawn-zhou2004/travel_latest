from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import new_uuid, utc_now
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.modules.admin.models import AdminAction
from app.modules.memberships.models import MembershipPlan, UserEntitlement, UserMembership
from app.modules.memberships.schemas import MembershipGrantCreate, MembershipPlanCreate, MembershipPlanUpdate


MEMBERSHIP_ENTITLEMENT_UPDATED = "membership.entitlement_updated"


class MembershipError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code


def effective_membership_status(membership: UserMembership, now: datetime | None = None) -> str:
    now = now or utc_now()
    valid_from = _as_utc(membership.valid_from)
    valid_until = _as_utc(membership.valid_until)
    if membership.status == "revoked":
        return "revoked"
    if membership.status == "expired" or now < valid_from or now >= valid_until:
        return "expired"
    return "active"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MembershipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_plan(self, body: MembershipPlanCreate, actor_id: str) -> MembershipPlan:
        existing = await self.session.scalar(select(MembershipPlan).where(MembershipPlan.code == body.code))
        if existing is not None:
            raise MembershipError("MEMBERSHIP_PLAN_CODE_EXISTS", "A membership plan already uses this code.")
        plan = MembershipPlan(**body.model_dump())
        self.session.add(plan)
        await self.session.flush()
        self._audit(actor_id, "membership_plan.created", "membership_plan", plan.id, "Created membership plan.", {"status": plan.status, "code": plan.code})
        await self.session.commit()
        return plan

    async def publish_plan(self, plan_id: str, actor_id: str) -> MembershipPlan:
        plan = await self._locked_plan(plan_id)
        if plan.status != "draft":
            raise MembershipError("MEMBERSHIP_PLAN_PUBLISH_NOT_ALLOWED", "Only draft membership plans can be published.")
        plan.status = "published"
        self._audit(actor_id, "membership_plan.published", "membership_plan", plan.id, "Published membership plan.", {"status": plan.status})
        await self.session.commit()
        return plan

    async def update_plan(self, plan_id: str, body: MembershipPlanUpdate, actor_id: str) -> MembershipPlan:
        plan = await self._locked_plan(plan_id)
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            return plan
        if changes.get("purchasable") and plan.status != "published":
            raise MembershipError("MEMBERSHIP_PLAN_NOT_PURCHASABLE", "Only published membership plans can be purchasable.")
        for field, value in changes.items():
            setattr(plan, field, value)
        self._audit(actor_id, "membership_plan.updated", "membership_plan", plan.id, "Updated membership plan configuration.", {
            "updated_fields": sorted(changes),
            "purchasable": plan.purchasable,
        })
        await self.session.commit()
        return plan

    async def archive_plan(self, plan_id: str, actor_id: str) -> MembershipPlan:
        plan = await self._locked_plan(plan_id)
        if plan.status not in {"draft", "published"}:
            raise MembershipError("MEMBERSHIP_PLAN_ARCHIVE_NOT_ALLOWED", "This membership plan is already archived.")
        plan.status = "archived"
        plan.purchasable = False
        self._audit(actor_id, "membership_plan.archived", "membership_plan", plan.id, "Archived membership plan.", {"status": plan.status, "purchasable": False})
        await self.session.commit()
        return plan

    async def grant(self, body: MembershipGrantCreate, actor_id: str, idempotency_key: str) -> UserMembership:
        existing = await self.session.scalar(select(UserMembership).where(
            UserMembership.granted_by == actor_id,
            UserMembership.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            if existing.user_id != body.user_id or existing.plan_id != body.plan_id or (
                body.valid_from is not None and _as_utc(existing.valid_from) != body.valid_from
            ):
                raise MembershipError("IDEMPOTENCY_CONFLICT", "Idempotency-Key is already bound to another membership grant.")
            return existing
        plan = await self._locked_plan(body.plan_id)
        if plan.status != "published":
            raise MembershipError("MEMBERSHIP_PLAN_NOT_GRANTABLE", "Only published membership plans can be granted.")
        if await self.session.get(User, body.user_id) is None:
            raise MembershipError("USER_NOT_FOUND", "The user is unavailable.", 404)
        valid_from = body.valid_from or utc_now()
        valid_until = valid_from + timedelta(days=plan.duration_days)
        membership = UserMembership(
            user_id=body.user_id,
            plan_id=plan.id,
            valid_from=valid_from,
            valid_until=valid_until,
            grant_source="admin_grant",
            granted_by=actor_id,
            idempotency_key=idempotency_key,
        )
        self.session.add(membership)
        await self.session.flush()
        self.session.add_all(
            UserEntitlement(
                membership_id=membership.id,
                user_id=membership.user_id,
                entitlement_code=code,
                valid_from=valid_from,
                valid_until=valid_until,
            )
            for code in plan.entitlement_codes
        )
        self._audit(actor_id, "membership.granted", "user_membership", membership.id, body.reason, {
            "user_id": membership.user_id,
            "plan_id": plan.id,
            "valid_until": valid_until.isoformat(),
        })
        self._enqueue(membership)
        await self.session.commit()
        return membership

    async def revoke(self, membership_id: str, actor_id: str, reason: str) -> UserMembership:
        membership = await self.session.scalar(select(UserMembership).where(UserMembership.id == membership_id).with_for_update())
        if membership is None:
            raise MembershipError("MEMBERSHIP_NOT_FOUND", "The membership is unavailable.", 404)
        if effective_membership_status(membership) != "active":
            raise MembershipError("MEMBERSHIP_REVOKE_NOT_ALLOWED", "Only active memberships can be revoked.")
        membership.status = "revoked"
        membership.revoked_by = actor_id
        membership.revoked_at = utc_now()
        membership.revoke_reason = reason
        self._audit(actor_id, "membership.revoked", "user_membership", membership.id, reason, {
            "user_id": membership.user_id,
            "status": membership.status,
            "valid_until": membership.valid_until.isoformat(),
        })
        self._enqueue(membership)
        await self.session.commit()
        return membership

    async def _locked_plan(self, plan_id: str) -> MembershipPlan:
        plan = await self.session.scalar(select(MembershipPlan).where(MembershipPlan.id == plan_id).with_for_update())
        if plan is None:
            raise MembershipError("MEMBERSHIP_PLAN_NOT_FOUND", "The membership plan is unavailable.", 404)
        return plan

    def _audit(self, actor_id: str, action: str, target_type: str, target_id: str, reason: str, result: dict[str, object]) -> None:
        self.session.add(AdminAction(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            result_json=result,
        ))

    def _enqueue(self, membership: UserMembership) -> None:
        self.session.add(OutboxEvent(
            event_type=MEMBERSHIP_ENTITLEMENT_UPDATED,
            aggregate_type="user_membership",
            aggregate_id=membership.id,
            trace_id=new_uuid(),
            payload_json={
                "user_id": membership.user_id,
                "membership_id": membership.id,
                "status": membership.status,
                "valid_until": membership.valid_until.isoformat(),
            },
        ))
