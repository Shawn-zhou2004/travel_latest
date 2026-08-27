import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import create_app
from app.models.base import Base
from app.models.user import User
from app.modules.auth.dependencies import get_auth_service
from app.modules.auth.service import AuthService, InMemoryTTLStore
from app.modules.memberships.models import MembershipPlan, UserEntitlement, UserMembership


def test_membership_routes_limit_public_data_and_return_effective_consumer_entitlements() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="membership-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000076")
            owner = User(phone="13600000077")
            other = User(phone="13600000078")
            session.add_all((admin, owner, other))
            await session.flush()
            published = MembershipPlan(code="published", name="Published", duration_days=30, entitlement_codes=["priority"], status="published")
            draft = MembershipPlan(code="draft", name="Draft", duration_days=30, entitlement_codes=["private"], status="draft")
            session.add_all((published, draft))
            await session.flush()
            now = datetime.now(UTC)
            active = UserMembership(
                user_id=owner.id, plan_id=published.id, valid_from=now - timedelta(minutes=1), valid_until=now + timedelta(days=1),
                granted_by=admin.id, idempotency_key="active",
            )
            revoked = UserMembership(
                user_id=owner.id, plan_id=published.id, status="revoked", valid_from=now - timedelta(minutes=1), valid_until=now + timedelta(days=1),
                granted_by=admin.id, idempotency_key="revoked",
            )
            expired = UserMembership(
                user_id=owner.id, plan_id=published.id, valid_from=now - timedelta(days=2), valid_until=now - timedelta(days=1),
                granted_by=admin.id, idempotency_key="expired",
            )
            session.add_all((active, revoked, expired))
            await session.flush()
            session.add_all((
                UserEntitlement(membership_id=active.id, user_id=owner.id, entitlement_code="priority", valid_from=active.valid_from, valid_until=active.valid_until),
                UserEntitlement(membership_id=revoked.id, user_id=owner.id, entitlement_code="revoked_code", valid_from=revoked.valid_from, valid_until=revoked.valid_until),
                UserEntitlement(membership_id=expired.id, user_id=owner.id, entitlement_code="expired_code", valid_from=expired.valid_from, valid_until=expired.valid_until),
            ))
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        owner_token = auth.create_access_token(user_id=owner.id, audience="consumer", roles=["user"])
        other_token = auth.create_access_token(user_id=other.id, audience="consumer", roles=["user"])
        try:
            with TestClient(app) as client:
                public = client.get("/api/v1/membership-plans")
                assert public.status_code == 200
                assert [item["code"] for item in public.json()] == ["published"]

                entitlements = client.get("/api/v1/users/me/entitlements", headers={"Authorization": f"Bearer {owner_token}"})
                assert entitlements.status_code == 200
                assert [item["code"] for item in entitlements.json()] == ["priority"]
                assert {"user_id", "granted_by", "revoke_reason"}.isdisjoint(entitlements.json()[0])

                own = client.get(f"/api/v1/memberships/{active.id}", headers={"Authorization": f"Bearer {owner_token}"})
                assert own.status_code == 200
                assert own.json()["status"] == "active"
                assert {"user_id", "granted_by", "revoke_reason"}.isdisjoint(own.json())
                assert client.get(f"/api/v1/memberships/{active.id}", headers={"Authorization": f"Bearer {other_token}"}).status_code == 404

                denied = client.get("/api/v1/admin/membership-plans", headers={"Authorization": f"Bearer {owner_token}"})
                assert denied.status_code == 403
                listed = client.get("/api/v1/admin/membership-plans", headers={"Authorization": f"Bearer {admin_token}"})
                assert listed.status_code == 200
                assert len(listed.json()["items"]) == 2
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_admin_can_create_publish_grant_and_revoke_membership() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        auth = AuthService(InMemoryTTLStore(), secret="membership-admin-router-test-secret")
        async with factory() as session:
            admin = User(phone="13600000079")
            user = User(phone="13600000080")
            session.add_all((admin, user))
            await session.commit()

        app = create_app()

        async def override_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_auth_service] = lambda: auth
        admin_token = auth.create_access_token(user_id=admin.id, audience="admin", roles=["platform_admin"])
        headers = {"Authorization": f"Bearer {admin_token}"}
        try:
            with TestClient(app) as client:
                created = client.post("/api/v1/admin/membership-plans", headers=headers, json={
                    "code": "operator-grant", "name": "Operator Grant", "duration_days": 7, "entitlement_codes": ["offline_maps"],
                    "price_amount": "9.90", "currency": "CNY", "generation_quota": 1, "assistant_quota": 20, "purchasable": False,
                })
                assert created.status_code == 201
                plan_id = created.json()["id"]
                assert created.json()["status"] == "draft"
                assert client.post(f"/api/v1/admin/membership-plans/{plan_id}:publish", headers=headers).status_code == 200
                grant_headers = {**headers, "Idempotency-Key": "operator-grant-1"}
                granted = client.post("/api/v1/admin/memberships", headers=grant_headers, json={
                    "user_id": user.id, "plan_id": plan_id, "reason": "Customer support adjustment.",
                })
                assert granted.status_code == 201
                membership_id = granted.json()["id"]
                repeated = client.post("/api/v1/admin/memberships", headers=grant_headers, json={
                    "user_id": user.id, "plan_id": plan_id, "reason": "Customer support adjustment.",
                })
                assert repeated.status_code == 201
                assert repeated.json()["id"] == membership_id
                revoked = client.post(
                    f"/api/v1/admin/memberships/{membership_id}:revoke",
                    headers=headers,
                    json={"reason": "Support correction."},
                )
                assert revoked.status_code == 200
                assert revoked.json()["status"] == "revoked"
                assert revoked.json()["revoke_reason"] == "Support correction."
        finally:
            await engine.dispose()

    asyncio.run(scenario())
