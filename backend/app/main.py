import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, StarletteHTTPException
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api.router import router
from app.core.database import SessionLocal
from app.core.errors import error_response
from app.core.request_context import reset_request_id, set_request_id
from app.core.settings import Settings
from app.models.user import User, UserRole
from app.modules.auth.service import AuthError, AuthService


# asyncpg and the LangGraph PostgreSQL checkpoint require a Selector loop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger("app.startup")


async def seed_fixed_admin() -> None:
    """Ensure the fixed backoffice account matches the configured credentials.

    The env values (ADMIN_USERNAME / ADMIN_PASSWORD) are the single source of
    truth: the account is created on first boot and its password is re-synced
    on every subsequent boot.
    """
    settings = Settings()
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.username == settings.admin_username))
        if user is None:
            # Placeholder phone: it can never collide with a real registration
            # because it fails the ^1[3-9]\d{9}$ pattern enforced everywhere.
            user = User(
                phone="10000000000",
                username=settings.admin_username,
                nickname="平台管理员",
                password_hash=AuthService.hash_password(settings.admin_password),
            )
            session.add(user)
            await session.flush()
            session.add(UserRole(user_id=user.id, role="platform_admin"))
        else:
            user.password_hash = AuthService.hash_password(settings.admin_password)
            roles = set(await session.scalars(select(UserRole.role).where(UserRole.user_id == user.id)))
            if "platform_admin" not in roles:
                session.add(UserRole(user_id=user.id, role="platform_admin"))
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if Settings().app_env != "test":
        try:
            await seed_fixed_admin()
        except Exception:
            # Startup must survive an unreachable database (e.g. first boot
            # before `docker compose up`); the seed retries on next start.
            logger.warning("Fixed admin account could not be seeded; the database is not reachable yet.", exc_info=True)
    yield


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID")
        try:
            UUID(request_id) if request_id else None
        except ValueError:
            request_id = None
        request_id = request_id or str(uuid4())
        request.state.request_id = request_id
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_request_id(token)


def create_app() -> FastAPI:
    app = FastAPI(title="AI Travel API", lifespan=lifespan)
    origins = [origin.strip() for origin in Settings().cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match-Version", "X-Operation-ID", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.include_router(router)

    @app.exception_handler(AuthError)
    async def handle_auth_error(request: Request, exc: AuthError) -> Response:
        return error_response(request, status_code=exc.status_code, code=exc.code, message=exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        return error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            details={"errors": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code") if isinstance(detail.get("code"), str) else None
        message = detail.get("message") if isinstance(detail.get("message"), str) else None
        details = detail.get("details") if isinstance(detail.get("details"), dict) else {}
        if exc.status_code == 404:
            return error_response(
                request,
                status_code=404,
                code=code or "NOT_FOUND",
                message=message or "Resource not found.",
                details=details,
            )
        return error_response(
            request,
            status_code=exc.status_code,
            code=code or "HTTP_ERROR",
            message=message or str(exc.detail),
            details=details,
        )

    return app


app = create_app()
