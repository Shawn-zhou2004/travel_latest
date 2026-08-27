from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User, UserRole
from app.modules.auth.router import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore

# Phones pre-seeded with user accounts; SMS login no longer auto-registers.
SEEDED_PHONES = ("13800138000", "13800138001", "13800138002", "13800138003")


@pytest.fixture
def client() -> TestClient:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    store = InMemoryTTLStore()
    app = create_app()

    async def override_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    asyncio.run(_create_tables(engine))
    asyncio.run(_seed_users(session_factory))
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


async def _create_tables(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _seed_users(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        for phone in SEEDED_PHONES:
            user = User(phone=phone)
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role="user"))
        await session.commit()
