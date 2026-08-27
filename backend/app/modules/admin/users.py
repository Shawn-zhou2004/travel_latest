import base64
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole, UserStatus
from app.modules.admin.schemas import AdminUserPage, AdminUserResponse, AdminUserUpdate


UNSCOPED_ROLES = {"user", "platform_admin"}
PROVIDER_ROLES = {"provider_admin", "provider_staff"}


def mask_phone(phone: str) -> str:
    if len(phone) <= 4:
        return "*" * len(phone)
    return f"{phone[:3]}****{phone[-4:]}"


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["created_at"]), payload["id"]
    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise HTTPException(422, detail={"code": "INVALID_CURSOR", "message": "The user directory cursor is invalid."}) from error


def _encode_cursor(user: User) -> str:
    payload = json.dumps({"created_at": user.created_at.isoformat(), "id": user.id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


async def list_admin_users(session: AsyncSession, query: str | None, limit: int, cursor: str | None) -> AdminUserPage:
    statement = select(User).order_by(User.created_at.asc(), User.id.asc())
    normalized_query = query.strip() if query else ""
    if normalized_query:
        statement = statement.where(User.phone.contains(normalized_query) | User.nickname.contains(normalized_query))
    decoded = _decode_cursor(cursor)
    if decoded:
        created_at, user_id = decoded
        statement = statement.where((User.created_at > created_at) | ((User.created_at == created_at) & (User.id > user_id)))
    users = (await session.scalars(statement.limit(limit + 1))).all()
    has_more = len(users) > limit
    users = users[:limit]
    if not users:
        return AdminUserPage(items=[])
    user_ids = [user.id for user in users]
    role_rows = (await session.execute(
        select(UserRole.user_id, UserRole.role, UserRole.scope_key)
        .where(UserRole.user_id.in_(user_ids))
        .order_by(UserRole.user_id.asc(), UserRole.role.asc(), UserRole.scope_key.asc())
    )).all()
    roles: dict[str, list[str]] = {user_id: [] for user_id in user_ids}
    memberships: dict[str, list[str]] = {user_id: [] for user_id in user_ids}
    for user_id, role, scope_key in role_rows:
        roles[user_id].append(role)
        if role in {"provider_admin", "provider_staff"} and scope_key:
            if scope_key not in memberships[user_id]:
                memberships[user_id].append(scope_key)
    return AdminUserPage(
        items=[AdminUserResponse(
            id=user.id, phone_masked=mask_phone(user.phone), nickname=user.nickname, status=UserStatus(user.status).value,
            roles=roles[user.id], provider_memberships=memberships[user.id],
            created_at=user.created_at, updated_at=user.updated_at,
        ) for user in users],
        next_cursor=_encode_cursor(users[-1]) if has_more else None,
    )


async def update_admin_user(session: AsyncSession, user_id: str, update: AdminUserUpdate) -> AdminUserResponse:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "The user is unavailable."})

    roles = list((await session.scalars(
        select(UserRole).where(UserRole.user_id == user_id).with_for_update()
    )).all())
    if update.roles is not None and PROVIDER_ROLES.intersection(update.roles):
        raise HTTPException(
            422,
            detail={
                "code": "PROVIDER_ROLE_SCOPE_REQUIRED",
                "message": "Provider roles require a provider scope and cannot be changed through this endpoint.",
            },
        )

    existing_unscoped = {role.role for role in roles if not role.scope_key}
    desired_unscoped = set(update.roles) if update.roles is not None else existing_unscoped
    if not desired_unscoped.issubset(UNSCOPED_ROLES):
        raise HTTPException(422, detail={"code": "INVALID_ROLE", "message": "Only unscoped roles can be changed through this endpoint."})
    removes_platform_admin = "platform_admin" in existing_unscoped and "platform_admin" not in desired_unscoped
    suspends_platform_admin = update.status == "suspended" and user.status == UserStatus.ACTIVE and "platform_admin" in existing_unscoped
    if removes_platform_admin or suspends_platform_admin:
        active_admins = list((await session.scalars(
            select(UserRole.user_id)
            .join(User, User.id == UserRole.user_id)
            .where(
                UserRole.role == "platform_admin",
                UserRole.scope_key == "",
                User.status == UserStatus.ACTIVE,
            )
            .with_for_update()
        )).all())
        if len(active_admins) == 1:
            raise HTTPException(
                409,
                detail={"code": "LAST_ACTIVE_PLATFORM_ADMIN", "message": "The last active platform admin cannot be suspended or removed."},
            )

    if update.status is not None:
        user.status = UserStatus(update.status)
    if update.roles is not None:
        for role in roles:
            if not role.scope_key and role.role in UNSCOPED_ROLES and role.role not in desired_unscoped:
                await session.delete(role)
        for role in desired_unscoped - existing_unscoped:
            session.add(UserRole(user_id=user.id, role=role))

    current_roles = sorted({role.role for role in roles if role.scope_key} | desired_unscoped)
    memberships = sorted({role.scope_key for role in roles if role.role in PROVIDER_ROLES and role.scope_key})
    return AdminUserResponse(
        id=user.id,
        phone_masked=mask_phone(user.phone),
        nickname=user.nickname,
        status=UserStatus(user.status).value,
        roles=current_roles,
        provider_memberships=memberships,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )
