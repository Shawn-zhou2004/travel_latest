from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import bcrypt

from app.core.settings import Settings
from app.integrations.aliyun_sms.client import AliyunSmsError, AliyunSmsSender, configured_aliyun_sms_sender


class TTLStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...
    def delete(self, key: str) -> None: ...
    def increment(self, key: str, ttl_seconds: int) -> int: ...


class InMemoryTTLStore:
    def __init__(self) -> None:
        self._values: MutableMapping[str, tuple[str, float]] = {}

    def get(self, key: str) -> str | None:
        value = self._values.get(key)
        if value is None or value[1] <= time.monotonic():
            self._values.pop(key, None)
            return None
        return value[0]

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._values[key] = (value, time.monotonic() + ttl_seconds)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def increment(self, key: str, ttl_seconds: int) -> int:
        value = int(self.get(key) or "0") + 1
        self.set(key, str(value), ttl_seconds)
        return value


class AuthError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


def _configured_jwt_secret() -> str | None:
    configured = os.getenv("JWT_SECRET")
    if configured:
        return configured
    try:
        return Settings().jwt_secret
    except ValueError:
        return None


def _configured_aliyun_sms_sender() -> AliyunSmsSender | None:
    try:
        return configured_aliyun_sms_sender(Settings())
    except ValueError:
        return None


# Aliyun provider codes that mean "too many sends", mapped to HTTP 429.
_PROVIDER_THROTTLE_CODES = {
    "biz.FREQUENCY",  # resend interval not elapsed
    "isv.BUSINESS_LIMIT_CONTROL",  # hourly/daily per-phone quota exceeded
    "isp.RATE_LIMIT",  # account-level rate limit
}


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    session_id: str
    audience: str
    roles: list[str]


class AuthService:
    def __init__(self, store: TTLStore, secret: str | None = None, sms_sender: AliyunSmsSender | None = None) -> None:
        self.store = store
        self.secret = (secret or _configured_jwt_secret() or "development-only-jwt-secret").encode()
        self.sms_sender = sms_sender if sms_sender is not None else _configured_aliyun_sms_sender()

    def send_sms_code(self, phone: str, ip: str, device: str) -> tuple[str, bool]:
        """Store a verification code and return (code, delivered).

        delivered is True when the code was sent through the SMS provider and
        False when a locally generated fallback code was used.
        """
        if self.store.get(f"auth:sms:throttle:{phone}"):
            raise AuthError(429, "SMS_THROTTLED", "Please wait before requesting another code.")
        self._check_rate_limit(f"auth:rate:phone:{phone}", 10, 3600)
        self._check_rate_limit(f"auth:rate:ip:{ip}", 50, 3600)
        self._check_rate_limit(f"auth:rate:device:{device}", 20, 3600)
        code, delivered = self._deliver_sms_code(phone)
        self.store.set(f"auth:sms:{phone}", code, 300)
        self.store.set(f"auth:sms:throttle:{phone}", "1", 60)
        return code, delivered

    def _deliver_sms_code(self, phone: str) -> tuple[str, bool]:
        """Deliver the code through Aliyun when configured, or fall back to a local code."""
        if self.sms_sender is None:
            return f"{secrets.randbelow(1_000_000):06d}", False
        try:
            code = self.sms_sender.send_verification_code(phone)
        except AliyunSmsError as error:
            if error.provider_code in _PROVIDER_THROTTLE_CODES:
                raise AuthError(429, "SMS_THROTTLED", "Please wait before requesting another code.") from error
            raise AuthError(502, "SMS_SEND_FAILED", "The verification code could not be sent. Please try again later.") from error
        return code, True

    def enforce_login_rate_limit(self, phone: str, ip: str, device: str) -> None:
        """Shared brute-force protection for every login path (SMS and password)."""
        self._check_rate_limit(f"auth:login:phone:{phone}", 10, 900)
        self._check_rate_limit(f"auth:login:ip:{ip}", 30, 900)
        self._check_rate_limit(f"auth:login:device:{device}", 15, 900)

    def verify_sms_code(self, phone: str, code: str, ip: str, device: str) -> None:
        self.enforce_login_rate_limit(phone, ip, device)
        stored_code = self.store.get(f"auth:sms:{phone}")
        if stored_code is None or not hmac.compare_digest(stored_code, code):
            raise AuthError(401, "INVALID_SMS_CODE", "The verification code is invalid or expired.")
        self.store.delete(f"auth:sms:{phone}")

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return False

    def create_access_token(self, *, user_id: str, audience: str, roles: list[str], session_id: str = "") -> str:
        now = int(time.time())
        payload = {"sub": user_id, "sid": session_id, "aud": audience, "roles": roles, "iat": now, "exp": now + 900}
        header = {"alg": "HS256", "typ": "JWT"}
        encoded_header = self._encode_json(header)
        encoded_payload = self._encode_json(payload)
        signing_input = f"{encoded_header}.{encoded_payload}".encode()
        signature = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
        return f"{encoded_header}.{encoded_payload}.{self._b64(signature)}"

    def parse_access_token(self, token: str, audience: str) -> AccessClaims:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".")
            signing_input = f"{encoded_header}.{encoded_payload}".encode()
            expected = self._b64(hmac.new(self.secret, signing_input, hashlib.sha256).digest())
            payload = json.loads(self._unb64(encoded_payload))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            raise AuthError(401, "INVALID_ACCESS_TOKEN", "Access token is invalid.") from None
        if not hmac.compare_digest(expected, encoded_signature) or payload.get("exp", 0) <= time.time():
            raise AuthError(401, "INVALID_ACCESS_TOKEN", "Access token is invalid or expired.")
        if payload.get("aud") != audience:
            raise AuthError(403, "INVALID_TOKEN_AUDIENCE", "This token cannot access this endpoint.")
        return AccessClaims(payload["sub"], payload.get("sid", ""), audience, list(payload.get("roles", [])))

    def new_refresh_token(self, session_id: str) -> tuple[str, str]:
        secret = secrets.token_urlsafe(32)
        token = f"{session_id}.{secret}"
        return token, self.hash_refresh_token(token)

    def hash_refresh_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_realtime_ticket(self, user_id: str, resource_type: str, resource_id: str) -> str:
        ticket = secrets.token_urlsafe(32)
        self.store.set(f"auth:ticket:{ticket}", json.dumps([user_id, resource_type, resource_id]), 60)
        return ticket

    def consume_realtime_ticket(self, ticket: str, user_id: str, resource_type: str, resource_id: str) -> bool:
        key = f"auth:ticket:{ticket}"
        value = self.store.get(key)
        self.store.delete(key)
        return value == json.dumps([user_id, resource_type, resource_id])

    def consume_realtime_ticket_for_resource(self, ticket: str, resource_type: str, resource_id: str) -> str | None:
        key = f"auth:ticket:{ticket}"
        value = self.store.get(key)
        self.store.delete(key)
        try:
            user_id, stored_type, stored_id = json.loads(value or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return str(user_id) if stored_type == resource_type and stored_id == resource_id else None

    def _check_rate_limit(self, key: str, maximum: int, ttl_seconds: int) -> None:
        if self.store.increment(key, ttl_seconds) > maximum:
            raise AuthError(429, "RATE_LIMITED", "Too many authentication attempts.")

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @classmethod
    def _encode_json(cls, value: dict[str, object]) -> str:
        return cls._b64(json.dumps(value, separators=(",", ":")).encode())

    @staticmethod
    def _unb64(value: str) -> str:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=30)
