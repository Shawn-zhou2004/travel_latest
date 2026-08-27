import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from starlette.responses import Response as StarletteResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.request_context import get_request_id
from app.core.settings import Settings
from app.models.user import User, UserRole, UserSession, UserStatus
from app.modules.auth.dependencies import CurrentAuthenticated, CurrentConsumer, get_auth_service
from app.modules.auth.schemas import (
    PasswordSessionRequest,
    RealtimeTicketRequest,
    RealtimeTicketResponse,
    RegisterRequest,
    SMSCodeRequest,
    SMSCodeResponse,
    SessionRefreshRequest,
    SessionRequest,
    SessionResponse,
    UserResponse,
)
from app.modules.auth.service import AuthError, AuthService, refresh_expiry


router = APIRouter(prefix="/auth", tags=["auth"])
realtime_router = APIRouter(tags=["realtime"])
Session = Annotated[AsyncSession, Depends(get_session)]
Service = Annotated[AuthService, Depends(get_auth_service)]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _device(request: Request, device_name: str | None = None) -> str:
    return device_name or request.headers.get("User-Agent", "unknown")[:128]


async def _user_response(session: AsyncSession, user: User) -> UserResponse:
    roles = list((await session.scalars(select(UserRole.role).where(UserRole.user_id == user.id))).all())
    return UserResponse(id=user.id, nickname=user.nickname, avatar_asset_id=user.avatar_asset_id, roles=roles or ["user"])


async def _issue_session(
    session: AsyncSession, service: AuthService, user: User, audience: str
) -> tuple[str, str, UserResponse]:
    if user.status == UserStatus.SUSPENDED:
        raise AuthError(403, "ACCOUNT_SUSPENDED", "This account is suspended.")
    user_response = await _user_response(session, user)
    if audience == "admin" and not {"platform_admin", "provider_admin", "provider_staff"}.intersection(user_response.roles):
        raise AuthError(403, "BACKOFFICE_ACCESS_REQUIRED", "A backoffice role is required for an admin audience token.")
    persisted = UserSession(user_id=user.id, refresh_token_hash="", expires_at=refresh_expiry())
    session.add(persisted)
    await session.flush()
    refresh_token, persisted.refresh_token_hash = service.new_refresh_token(persisted.id)
    access_token = service.create_access_token(
        user_id=user.id, session_id=persisted.id, audience=audience, roles=user_response.roles
    )
    await session.commit()
    return access_token, refresh_token, user_response


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        "refresh_token", refresh_token, max_age=30 * 24 * 60 * 60, httponly=True, secure=False, samesite="lax", path="/api/v1/auth"
    )


@router.post("/sms-codes", status_code=status.HTTP_202_ACCEPTED, response_model=SMSCodeResponse)
async def send_sms_code(body: SMSCodeRequest, request: Request, service: Service) -> SMSCodeResponse:
    code, delivered = service.send_sms_code(body.phone, _client_ip(request), _device(request))
    # Only echo the code for local fallback codes (no SMS provider configured);
    # real SMS deliveries must never leak the code back to the client.
    debug_code = None if delivered else (code if Settings().app_env in {"development", "test"} else None)
    return SMSCodeResponse(request_id=get_request_id(request), debug_code=debug_code)


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def register(body: RegisterRequest, request: Request, response: Response, session: Session, service: Service) -> SessionResponse:
    """Register with an SMS-verified phone and immediately start a session."""
    service.verify_sms_code(body.phone, body.code, _client_ip(request), _device(request, body.device_name))
    existing = await session.scalar(select(User).where(User.phone == body.phone))
    if existing is not None:
        raise AuthError(409, "PHONE_ALREADY_REGISTERED", "This phone number is already registered.")
    user = User(phone=body.phone, nickname=body.nickname, password_hash=service.hash_password(body.password))
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role="user"))
    access_token, refresh_token, user_response = await _issue_session(session, service, user, "consumer")
    _set_refresh_cookie(response, refresh_token)
    return SessionResponse(access_token=access_token, user=user_response, request_id=get_request_id(request))


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def create_session(body: SessionRequest, request: Request, response: Response, session: Session, service: Service) -> SessionResponse:
    service.verify_sms_code(body.phone, body.code, _client_ip(request), _device(request, body.device_name))
    user = await session.scalar(select(User).where(User.phone == body.phone))
    if user is None:
        raise AuthError(404, "PHONE_NOT_REGISTERED", "This phone number is not registered yet.")
    access_token, refresh_token, user_response = await _issue_session(session, service, user, body.audience)
    _set_refresh_cookie(response, refresh_token)
    return SessionResponse(access_token=access_token, user=user_response, request_id=get_request_id(request))


@router.post("/sessions/password", status_code=status.HTTP_201_CREATED, response_model=SessionResponse)
async def create_password_session(
    body: PasswordSessionRequest, request: Request, response: Response, session: Session, service: Service
) -> SessionResponse:
    # Fixed backoffice accounts identify by username; consumers by phone.
    identity = body.username or body.phone
    service.enforce_login_rate_limit(identity, _client_ip(request), _device(request, body.device_name))
    if body.username:
        user = await session.scalar(select(User).where(User.username == body.username))
        not_found = AuthError(404, "ACCOUNT_NOT_FOUND", "This account does not exist.")
    else:
        user = await session.scalar(select(User).where(User.phone == body.phone))
        not_found = AuthError(404, "PHONE_NOT_REGISTERED", "This phone number is not registered yet.")
    if user is None:
        raise not_found
    if user.password_hash is None:
        raise AuthError(401, "PASSWORD_NOT_SET", "This account has no password yet. Please log in with a verification code.")
    if not service.verify_password(body.password, user.password_hash):
        raise AuthError(401, "INVALID_CREDENTIALS", "The phone number or password is incorrect.")
    access_token, refresh_token, user_response = await _issue_session(session, service, user, body.audience)
    _set_refresh_cookie(response, refresh_token)
    return SessionResponse(access_token=access_token, user=user_response, request_id=get_request_id(request))


@router.post("/sessions/refresh", response_model=SessionResponse)
async def refresh_session(
    request: Request,
    response: Response,
    session: Session,
    service: Service,
    body: SessionRefreshRequest | None = None,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> SessionResponse:
    if not refresh_token or "." not in refresh_token:
        raise AuthError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired.")
    session_id = refresh_token.split(".", 1)[0]
    persisted = await session.get(UserSession, session_id)
    if persisted is None or persisted.revoked_at is not None:
        raise AuthError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired.")
    expires_at = persisted.expires_at.replace(tzinfo=UTC) if persisted.expires_at.tzinfo is None else persisted.expires_at
    if expires_at <= datetime.now(UTC):
        raise AuthError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired.")
    if not hmac.compare_digest(persisted.refresh_token_hash, service.hash_refresh_token(refresh_token)):
        raise AuthError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired.")
    user = await session.get(User, persisted.user_id)
    if user is None:
        raise AuthError(401, "INVALID_REFRESH_TOKEN", "Refresh token is invalid or expired.")
    persisted.revoked_at = datetime.now(UTC)
    audience = body.audience if body is not None else "consumer"
    access_token, new_refresh_token, user_response = await _issue_session(session, service, user, audience)
    _set_refresh_cookie(response, new_refresh_token)
    return SessionResponse(access_token=access_token, user=user_response, request_id=get_request_id(request))


@router.delete("/sessions/current", status_code=status.HTTP_204_NO_CONTENT)
async def delete_current_session(claims: CurrentAuthenticated, session: Session) -> StarletteResponse:
    if claims.session_id:
        persisted = await session.get(UserSession, claims.session_id)
        if persisted is not None:
            from app.models.base import utc_now

            persisted.revoked_at = utc_now()
            await session.commit()
    response = StarletteResponse(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return response


@router.get("/me", response_model=UserResponse)
async def get_me(claims: CurrentAuthenticated, session: Session) -> UserResponse:
    user = await session.get(User, claims.user_id)
    if user is None:
        raise AuthError(401, "AUTHENTICATION_REQUIRED", "The authenticated user no longer exists.")
    return await _user_response(session, user)


@realtime_router.post("/realtime-tickets", status_code=status.HTTP_201_CREATED, response_model=RealtimeTicketResponse)
async def create_realtime_ticket(body: RealtimeTicketRequest, request: Request, claims: CurrentConsumer, service: Service) -> RealtimeTicketResponse:
    ticket = service.create_realtime_ticket(claims.user_id, body.resource_type, body.resource_id)
    return RealtimeTicketResponse(ticket=ticket, request_id=get_request_id(request))
