from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import UserRole
from app.seed import DEMO_PROVIDER_SCOPE, seed_development


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as database_session:
        yield database_session
    await engine.dispose()


@pytest.mark.anyio
async def test_development_seed_is_idempotent_and_has_no_passwords(session: AsyncSession) -> None:
    first = await seed_development(session)
    second = await seed_development(session)

    roles = list((await session.scalars(select(UserRole))).all())
    assert first == second
    assert {(role.role, role.scope_key) for role in roles} == {
        ("platform_admin", ""),
        ("provider_admin", DEMO_PROVIDER_SCOPE),
    }
