from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.user import User, UserSettings
from app.modules.ai_entitlements.service import AIEntitlementService
from app.modules.ai_memory.router import get_ai_memory_service
from app.modules.ai_memory.schemas import MemoryResponse
from app.modules.ai_memory.service import AIMemoryService
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.media.models import MediaAsset
from app.modules.users.schemas import AIEntitlementBalanceResponse, AIEntitlementsResponse, ProfileResponse, ProfileUpdateRequest, SettingsResponse, SettingsUpdateRequest


router = APIRouter(prefix="/users", tags=["users"])
Session = Annotated[AsyncSession, Depends(get_session)]
MemoryService = Annotated[AIMemoryService, Depends(get_ai_memory_service)]


def _profile(user: User) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        phone=user.phone,
        nickname=user.nickname,
        avatar_asset_id=user.avatar_asset_id,
    )


async def _settings(session: AsyncSession, user_id: str) -> UserSettings:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        await session.flush()
    return settings


@router.get("/me/ai-entitlements", response_model=AIEntitlementsResponse)
async def get_ai_entitlements(claims: CurrentConsumer, session: Session) -> AIEntitlementsResponse:
    free, membership = await AIEntitlementService(session).balances(claims.user_id)
    return AIEntitlementsResponse(
        free=AIEntitlementBalanceResponse(
            source=free.source,
            itinerary_generation_remaining=free.itinerary_generation_remaining,
            assistant_message_remaining=free.assistant_message_remaining,
            period_end=free.period_end,
        ),
        membership=AIEntitlementBalanceResponse(
            source=membership.source,
            itinerary_generation_remaining=membership.itinerary_generation_remaining,
            assistant_message_remaining=membership.assistant_message_remaining,
            period_end=membership.period_end,
        ) if membership else None,
    )


@router.get("/me/settings", response_model=SettingsResponse)
async def get_settings(claims: CurrentConsumer, session: Session) -> SettingsResponse:
    settings = await _settings(session, claims.user_id)
    await session.commit()
    await session.refresh(settings)
    return SettingsResponse.model_validate(settings)


@router.patch("/me/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdateRequest, claims: CurrentConsumer, session: Session) -> SettingsResponse:
    if not body.model_fields_set:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "At least one settings field is required."})
    non_nullable_fields = body.model_fields_set - {"departure_city"}
    if any(getattr(body, field_name) is None for field_name in non_nullable_fields):
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "Settings values must not be null."})
    settings = await _settings(session, claims.user_id)
    for field_name in body.model_fields_set:
        value = getattr(body, field_name)
        if field_name == "departure_city" and value is not None:
            value = value.strip() or None
        setattr(settings, field_name, value)
    await session.commit()
    await session.refresh(settings)
    return SettingsResponse.model_validate(settings)


@router.post("/me/settings:sync-ai-memory", response_model=MemoryResponse)
async def sync_settings_to_ai_memory(claims: CurrentConsumer, session: Session, memory_service: MemoryService) -> MemoryResponse:
    settings = await _settings(session, claims.user_id)
    memory = await memory_service.sync_travel_profile(claims.user_id, {
        "departure_city": settings.departure_city,
        "interest_tags": list(settings.interest_tags),
        "travel_pace": settings.travel_pace,
        "traveler_type": settings.traveler_type,
    })
    await session.commit()
    return MemoryResponse.model_validate(memory)


@router.patch("/me", response_model=ProfileResponse)
async def update_profile(body: ProfileUpdateRequest, claims: CurrentConsumer, session: Session) -> ProfileResponse:
    if not body.model_fields_set:
        raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "At least one profile field is required."})
    user = await session.get(User, claims.user_id)
    if user is None:
        raise HTTPException(401, detail={"code": "AUTHENTICATION_REQUIRED", "message": "The authenticated user no longer exists."})
    if "avatar_asset_id" in body.model_fields_set and body.avatar_asset_id is not None:
        asset = await session.get(MediaAsset, body.avatar_asset_id)
        if asset is None or asset.owner_id != user.id:
            raise HTTPException(404, detail={"code": "MEDIA_ASSET_NOT_FOUND", "message": "The media asset is unavailable."})
        if asset.status != "completed":
            raise HTTPException(409, detail={"code": "MEDIA_ASSET_NOT_COMPLETED", "message": "The media asset upload is not complete."})
    if "nickname" in body.model_fields_set:
        user.nickname = body.nickname
    if "avatar_asset_id" in body.model_fields_set:
        user.avatar_asset_id = body.avatar_asset_id
    await session.commit()
    await session.refresh(user)
    return _profile(user)
