from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, UUIDPrimaryKeyMixin, utc_now


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="ck_users_status"),
    )

    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    # Nullable: only fixed backoffice accounts log in with a username.
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # Nullable: legacy accounts created through SMS-only login have no password yet.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[UserStatus] = mapped_column(String(16), nullable=False, default=UserStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("budget_level IN ('economy', 'balanced', 'premium')", name="ck_user_settings_budget_level"),
        CheckConstraint("travel_pace IN ('relaxed', 'balanced', 'packed')", name="ck_user_settings_travel_pace"),
        CheckConstraint("traveler_type IN ('solo', 'couple', 'friends', 'family')", name="ck_user_settings_traveler_type"),
        CheckConstraint("profile_visibility IN ('private', 'collaborators')", name="ck_user_settings_profile_visibility"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    departure_city: Mapped[str | None] = mapped_column(String(128))
    budget_level: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")
    travel_pace: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced")
    interest_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    traveler_type: Mapped[str] = mapped_column(String(16), nullable=False, default="friends")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    itinerary_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    community_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    profile_visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="collaborators")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)

    def __init__(self, **kwargs: object) -> None:
        defaults = {
            "budget_level": "balanced",
            "travel_pace": "balanced",
            "interest_tags": [],
            "traveler_type": "friends",
            "notifications_enabled": True,
            "order_notifications": True,
            "itinerary_notifications": True,
            "community_notifications": True,
            "profile_visibility": "collaborators",
        }
        for field_name, value in defaults.items():
            kwargs.setdefault(field_name, value)
        super().__init__(**kwargs)


class UserSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)


class UserRole(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'platform_admin', 'provider_admin', 'provider_staff')",
            name="ck_user_roles_role",
        ),
        UniqueConstraint("user_id", "role", "scope_key", name="uq_user_roles_user_role_scope"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)

    def __init__(self, **kwargs: object) -> None:
        if kwargs.get("scope_key") is None:
            kwargs["scope_key"] = ""
        super().__init__(**kwargs)
