from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal, engine
from app.core.settings import Settings
from app.models.user import User, UserRole


DEMO_PROVIDER_SCOPE = "00000000-0000-4000-8000-000000000001"
DEFAULT_ADMIN_PHONE = "15500000001"
DEFAULT_PROVIDER_PHONE = "15500000002"


async def _get_or_create_user(session: AsyncSession, phone: str) -> User:
    user = await session.scalar(select(User).where(User.phone == phone))
    if user is None:
        user = User(phone=phone)
        session.add(user)
        await session.flush()
    return user


async def _ensure_role(
    session: AsyncSession, user_id: str, role: str, scope_key: str = ""
) -> UserRole:
    existing = await session.scalar(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role == role,
            UserRole.scope_key == scope_key,
        )
    )
    if existing is not None:
        return existing
    authority = UserRole(user_id=user_id, role=role, scope_key=scope_key)
    session.add(authority)
    return authority


async def seed_development(
    session: AsyncSession,
    *,
    admin_phone: str = DEFAULT_ADMIN_PHONE,
    provider_phone: str = DEFAULT_PROVIDER_PHONE,
) -> dict[str, str]:
    """Create deterministic role fixtures without passwords or third-party secrets."""

    admin = await _get_or_create_user(session, admin_phone)
    provider = await _get_or_create_user(session, provider_phone)
    await _ensure_role(session, admin.id, "platform_admin")
    await _ensure_role(session, provider.id, "provider_admin", DEMO_PROVIDER_SCOPE)
    await session.commit()
    return {"platform_admin_id": admin.id, "demo_provider_user_id": provider.id}


async def _run_seed() -> dict[str, str]:
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("Development seed is disabled outside development/test environments")
    try:
        async with SessionLocal() as session:
            return await seed_development(
                session,
                admin_phone=os.getenv("SEED_PLATFORM_ADMIN_PHONE", DEFAULT_ADMIN_PHONE),
                provider_phone=os.getenv("SEED_DEMO_PROVIDER_PHONE", DEFAULT_PROVIDER_PHONE),
            )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create deterministic development fixtures")
    parser.parse_args(argv)
    print(asyncio.run(_run_seed()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
