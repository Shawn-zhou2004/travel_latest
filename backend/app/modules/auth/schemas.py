from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SMSCodeRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    captcha_token: str | None = None


class SMSCodeResponse(BaseModel):
    request_id: str
    expires_in: Literal[300] = 300
    debug_code: str | None = None


class SessionRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    # Provider-generated codes are 4-6 digits even though we request 6.
    code: str = Field(pattern=r"^\d{4,6}$")
    device_name: str | None = Field(default=None, max_length=128)
    audience: Literal["consumer", "admin"] = "consumer"


class RegisterRequest(BaseModel):
    """Registration with SMS-verified phone; the nickname is display-only."""

    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    code: str = Field(pattern=r"^\d{4,6}$")
    nickname: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=64)
    device_name: str | None = Field(default=None, max_length=128)


class PasswordSessionRequest(BaseModel):
    """Password login by phone (consumer) or username (fixed backoffice accounts)."""

    phone: str | None = Field(default=None, pattern=r"^1[3-9]\d{9}$")
    username: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=1, max_length=64)
    device_name: str | None = Field(default=None, max_length=128)
    audience: Literal["consumer", "admin"] = "consumer"

    @model_validator(mode="after")
    def require_phone_or_username(self) -> "PasswordSessionRequest":
        if not self.phone and not self.username:
            raise ValueError("Either phone or username is required.")
        return self


class SessionRefreshRequest(BaseModel):
    audience: Literal["consumer", "admin"] = "consumer"


class UserResponse(BaseModel):
    id: str
    nickname: str | None = None
    avatar_asset_id: str | None = None
    roles: list[str]
    provider_memberships: list[str] = Field(default_factory=list)
    entitlements: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: Literal[900] = 900
    user: UserResponse
    request_id: str


class RealtimeTicketRequest(BaseModel):
    resource_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    resource_id: str = Field(min_length=1, max_length=128)


class RealtimeTicketResponse(BaseModel):
    ticket: str
    expires_in: Literal[60] = 60
    request_id: str
