from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.integrations.aliyun_sms.client import AliyunSmsError
from app.modules.auth.dependencies import current_admin_claims, current_backoffice_claims
from app.modules.auth.router import get_auth_service
from app.modules.auth.service import AuthError, AuthService, InMemoryTTLStore
from app.models.user import User, UserRole, UserStatus


def test_sms_login_sets_refresh_cookie_and_returns_consumer_access_token(client: TestClient) -> None:
    response = client.post("/api/v1/auth/sms-codes", json={"phone": "13800138000"})
    assert response.status_code == 202
    assert response.json()["debug_code"] is not None

    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138000", "123456", 300)
    response = client.post(
        "/api/v1/auth/sessions",
        json={"phone": "13800138000", "code": "123456", "device_name": "pytest"},
        headers={"Idempotency-Key": "login-1"},
    )

    assert response.status_code == 201
    assert response.json()["token_type"] == "Bearer"
    assert "httponly" in response.headers["set-cookie"].lower()
    assert response.json()["user"]["roles"] == ["user"]


def test_refresh_rotates_session_and_logout_revokes_it(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138000", "123456", 300)
    login = client.post("/api/v1/auth/sessions", json={"phone": "13800138000", "code": "123456"})
    access_token = login.json()["access_token"]
    logout = client.delete("/api/v1/auth/sessions/current", headers={"Authorization": f"Bearer {access_token}"})
    assert logout.status_code == 204
    assert client.post("/api/v1/auth/sessions/refresh").status_code == 401


def test_refresh_rotates_session(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138000", "123456", 300)
    login = client.post("/api/v1/auth/sessions", json={"phone": "13800138000", "code": "123456"})
    refresh = client.post("/api/v1/auth/sessions/refresh")

    assert refresh.status_code == 200
    assert refresh.headers["set-cookie"] != login.headers["set-cookie"]


def test_admin_audience_can_use_shared_session_logout_endpoint(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    token = service.create_access_token(user_id="user-1", audience="admin", roles=["platform_admin"])
    response = client.delete("/api/v1/auth/sessions/current", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204


def test_session_issues_requested_consumer_audience_by_default(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138001", "123456", 300)

    response = client.post("/api/v1/auth/sessions", json={"phone": "13800138001", "code": "123456"})

    claims = service.parse_access_token(response.json()["access_token"], "consumer")
    assert claims.audience == "consumer"


def test_session_rejects_admin_audience_for_consumer_only_user(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138002", "123456", 300)

    response = client.post(
        "/api/v1/auth/sessions",
        json={"phone": "13800138002", "code": "123456", "audience": "admin"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "BACKOFFICE_ACCESS_REQUIRED"


def test_session_and_refresh_reject_suspended_user(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138003", "123456", 300)
    login = client.post("/api/v1/auth/sessions", json={"phone": "13800138003", "code": "123456"})
    assert login.status_code == 201

    override_session = client.app.dependency_overrides[get_session]

    async def suspend() -> None:
        async for session in override_session():
            assert isinstance(session, AsyncSession)
            user = await session.scalar(select(User).where(User.phone == "13800138003"))
            assert user is not None
            user.status = UserStatus.SUSPENDED
            await session.commit()

    asyncio.run(suspend())
    assert client.post("/api/v1/auth/sessions/refresh").json()["code"] == "ACCOUNT_SUSPENDED"
    service.store.set("auth:sms:13800138003", "123456", 300)
    response = client.post("/api/v1/auth/sessions", json={"phone": "13800138003", "code": "123456"})
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_SUSPENDED"


def test_backoffice_dependency_allows_only_backoffice_roles(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    for role in ("platform_admin", "provider_admin", "provider_staff"):
        token = service.create_access_token(user_id=f"{role}-1", audience="admin", roles=[role])
        assert current_backoffice_claims(token, service).user_id == f"{role}-1"

    provider_token = service.create_access_token(user_id="provider-1", audience="admin", roles=["provider_staff"])
    try:
        current_admin_claims(provider_token, service)
        assert False, "provider staff must not satisfy the platform admin dependency"
    except AuthError as error:
        assert error.status_code == 403
        assert error.code == "FORBIDDEN"

    platform_token = service.create_access_token(user_id="admin-1", audience="admin", roles=["platform_admin"])
    assert current_admin_claims(platform_token, service).user_id == "admin-1"


class _FakeAliyunSender:
    def __init__(self, code: str = "654321", error: Exception | None = None) -> None:
        self.code = code
        self.error = error
        self.sent_phones: list[str] = []

    def send_verification_code(self, phone: str) -> str:
        self.sent_phones.append(phone)
        if self.error is not None:
            raise self.error
        return self.code


def test_sms_sender_code_is_stored_and_logs_in(client: TestClient) -> None:
    fake = _FakeAliyunSender(code="778899")
    store = InMemoryTTLStore()
    client.app.dependency_overrides[get_auth_service] = lambda: AuthService(store, secret="sms-sender-test-secret", sms_sender=fake)

    response = client.post("/api/v1/auth/sms-codes", json={"phone": "13800138000"})
    assert response.status_code == 202
    assert fake.sent_phones == ["13800138000"]
    # Real deliveries never echo the code back to the client.
    assert response.json()["debug_code"] is None
    login = client.post("/api/v1/auth/sessions", json={"phone": "13800138000", "code": "778899"})
    assert login.status_code == 201


def test_sms_login_accepts_provider_code_length_between_4_and_6(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138000", "4321", 300)
    login = client.post("/api/v1/auth/sessions", json={"phone": "13800138000", "code": "4321"})
    assert login.status_code == 201


def test_sms_sender_failure_returns_502(client: TestClient) -> None:
    store = InMemoryTTLStore()
    fake = _FakeAliyunSender(error=AliyunSmsError("isv.SMS_SIGNATURE_ILLEGAL", "bad signature"))
    client.app.dependency_overrides[get_auth_service] = lambda: AuthService(store, secret="sms-failure-test-secret", sms_sender=fake)

    response = client.post("/api/v1/auth/sms-codes", json={"phone": "13800138000"})
    assert response.status_code == 502
    assert response.json()["code"] == "SMS_SEND_FAILED"
    assert store.get("auth:sms:13800138000") is None


def test_sms_sender_frequency_error_returns_429(client: TestClient) -> None:
    store = InMemoryTTLStore()
    fake = _FakeAliyunSender(error=AliyunSmsError("biz.FREQUENCY", "check frequency failed"))
    client.app.dependency_overrides[get_auth_service] = lambda: AuthService(store, secret="sms-frequency-test-secret", sms_sender=fake)

    response = client.post("/api/v1/auth/sms-codes", json={"phone": "13800138000"})
    assert response.status_code == 429
    assert response.json()["code"] == "SMS_THROTTLED"


def test_sms_sender_business_limit_returns_429(client: TestClient) -> None:
    store = InMemoryTTLStore()
    fake = _FakeAliyunSender(error=AliyunSmsError("isv.BUSINESS_LIMIT_CONTROL", "business limit"))
    client.app.dependency_overrides[get_auth_service] = lambda: AuthService(store, secret="sms-limit-test-secret", sms_sender=fake)

    response = client.post("/api/v1/auth/sms-codes", json={"phone": "13800138000"})
    assert response.status_code == 429
    assert response.json()["code"] == "SMS_THROTTLED"


def test_sms_login_rejects_unregistered_phone(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13900139000", "123456", 300)

    response = client.post("/api/v1/auth/sessions", json={"phone": "13900139000", "code": "123456"})

    assert response.status_code == 404
    assert response.json()["code"] == "PHONE_NOT_REGISTERED"


def test_register_creates_user_and_starts_session(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13900139001", "123456", 300)

    response = client.post(
        "/api/v1/auth/register",
        json={"phone": "13900139001", "code": "123456", "nickname": "旅行者", "password": "secure-pass-1"},
    )

    assert response.status_code == 201
    assert response.json()["user"]["nickname"] == "旅行者"
    assert response.json()["user"]["roles"] == ["user"]
    assert "httponly" in response.headers["set-cookie"].lower()

    async def check_user() -> None:
        async for session in client.app.dependency_overrides[get_session]():
            user = await session.scalar(select(User).where(User.phone == "13900139001"))
            assert user is not None
            assert user.nickname == "旅行者"
            assert user.password_hash is not None
            assert AuthService.verify_password("secure-pass-1", user.password_hash)

    asyncio.run(check_user())
    # The SMS code is consumed by registration and cannot be reused.
    assert service.store.get("auth:sms:13900139001") is None


def test_register_rejects_duplicate_phone(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13800138000", "123456", 300)

    response = client.post(
        "/api/v1/auth/register",
        json={"phone": "13800138000", "code": "123456", "nickname": "重复注册", "password": "secure-pass-1"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PHONE_ALREADY_REGISTERED"


def test_register_rejects_invalid_code(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13900139002", "123456", 300)

    response = client.post(
        "/api/v1/auth/register",
        json={"phone": "13900139002", "code": "000000", "nickname": "验证码错误", "password": "secure-pass-1"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_SMS_CODE"


def test_password_login_succeeds_for_registered_user(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13900139003", "123456", 300)
    registered = client.post(
        "/api/v1/auth/register",
        json={"phone": "13900139003", "code": "123456", "nickname": "密码用户", "password": "secure-pass-1"},
    )
    assert registered.status_code == 201

    response = client.post("/api/v1/auth/sessions/password", json={"phone": "13900139003", "password": "secure-pass-1"})

    assert response.status_code == 201
    assert response.json()["user"]["nickname"] == "密码用户"
    assert "httponly" in response.headers["set-cookie"].lower()


def test_password_login_rejects_wrong_password(client: TestClient) -> None:
    service = client.app.dependency_overrides[get_auth_service]()
    service.store.set("auth:sms:13900139004", "123456", 300)
    registered = client.post(
        "/api/v1/auth/register",
        json={"phone": "13900139004", "code": "123456", "nickname": "密码用户", "password": "secure-pass-1"},
    )
    assert registered.status_code == 201

    response = client.post("/api/v1/auth/sessions/password", json={"phone": "13900139004", "password": "wrong-pass"})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_password_login_rejects_unregistered_phone(client: TestClient) -> None:
    response = client.post("/api/v1/auth/sessions/password", json={"phone": "13900139005", "password": "whatever"})

    assert response.status_code == 404
    assert response.json()["code"] == "PHONE_NOT_REGISTERED"


def test_password_login_rejects_account_without_password(client: TestClient) -> None:
    # Seeded legacy accounts were created through SMS-only login and have no password.
    response = client.post("/api/v1/auth/sessions/password", json={"phone": "13800138000", "password": "whatever"})

    assert response.status_code == 401
    assert response.json()["code"] == "PASSWORD_NOT_SET"


def _seed_backoffice_account(client: TestClient, username: str, password: str, role: str = "platform_admin") -> None:
    """Create a fixed backoffice account directly, mirroring the startup seed."""
    from app.modules.auth.service import AuthService

    async def seed() -> None:
        async for session in client.app.dependency_overrides[get_session]():
            user = User(
                phone=f"1000000000{len(username) % 10}",
                username=username,
                nickname="平台管理员",
                password_hash=AuthService.hash_password(password),
            )
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role=role))
            await session.commit()

    asyncio.run(seed())


def test_username_password_login_issues_admin_session(client: TestClient) -> None:
    _seed_backoffice_account(client, "admin", "admin123456")
    service = client.app.dependency_overrides[get_auth_service]()

    response = client.post(
        "/api/v1/auth/sessions/password",
        json={"username": "admin", "password": "admin123456", "audience": "admin"},
    )

    assert response.status_code == 201
    assert response.json()["user"]["roles"] == ["platform_admin"]
    claims = service.parse_access_token(response.json()["access_token"], "admin")
    assert claims.audience == "admin"
    assert "httponly" in response.headers["set-cookie"].lower()


def test_username_password_login_rejects_wrong_password(client: TestClient) -> None:
    _seed_backoffice_account(client, "admin", "admin123456")

    response = client.post(
        "/api/v1/auth/sessions/password",
        json={"username": "admin", "password": "wrong-pass", "audience": "admin"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_username_password_login_rejects_unknown_username(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/sessions/password",
        json={"username": "nobody", "password": "whatever", "audience": "admin"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ACCOUNT_NOT_FOUND"


def test_username_password_login_requires_backoffice_role_for_admin_audience(client: TestClient) -> None:
    _seed_backoffice_account(client, "operator", "operator-pass", role="user")

    response = client.post(
        "/api/v1/auth/sessions/password",
        json={"username": "operator", "password": "operator-pass", "audience": "admin"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "BACKOFFICE_ACCESS_REQUIRED"


def test_password_login_requires_phone_or_username(client: TestClient) -> None:
    response = client.post("/api/v1/auth/sessions/password", json={"password": "whatever"})

    assert response.status_code == 422
