from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.auth.router import realtime_router, router as auth_router
from app.modules.ai_memory.router import router as ai_memory_router
from app.modules.ai_workflows.router import router as ai_workflows_router
from app.modules.admin.router import router as admin_router
from app.modules.chat.router import router as chat_router
from app.modules.chat.websocket import websocket_router as chat_websocket_router
from app.modules.community.router import (
    companion_application_router,
    companion_router,
    moderation_router,
    router as community_router,
    users_router,
)
from app.modules.destinations.router import router as destinations_router
from app.modules.itineraries.router import router as itineraries_router
from app.modules.maps.router import router as maps_router
from app.modules.media.router import router as media_router
from app.modules.memberships.router import router as memberships_router
from app.modules.membership_purchases.router import router as membership_purchases_router
from app.modules.notifications.router import router as notifications_router
from app.modules.exports.router import router as exports_router
from app.modules.orders.router import router as orders_router
from app.modules.providers.router import router as providers_router
from app.modules.users.router import router as users_router
from app.modules.search.router import router as search_router


class HealthResponse(BaseModel):
    status: str
    service: str


router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(realtime_router)
router.include_router(ai_memory_router)
router.include_router(ai_workflows_router)
router.include_router(admin_router)
router.include_router(itineraries_router)
router.include_router(destinations_router)
router.include_router(maps_router)
router.include_router(media_router)
router.include_router(memberships_router)
router.include_router(membership_purchases_router)
router.include_router(notifications_router)
router.include_router(exports_router)
router.include_router(community_router)
router.include_router(companion_router)
router.include_router(companion_application_router)
router.include_router(moderation_router)
router.include_router(users_router)
router.include_router(chat_router)
router.include_router(search_router)
router.include_router(orders_router)
router.include_router(providers_router)
router.include_router(users_router)
router.include_router(chat_websocket_router)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="ai-travel-api")
