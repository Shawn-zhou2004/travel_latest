from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.auth.dependencies import CurrentConsumer
from app.modules.trip_support.schemas import (
    BudgetCreateRequest, BudgetItemResponse, BudgetListResponse, BudgetTotalResponse, BudgetUpdateRequest,
    ChecklistCreateRequest, ChecklistItemResponse, ChecklistListResponse, ChecklistUpdateRequest,
)
from app.modules.trip_support.service import TripSupportService

router = APIRouter(tags=["trip-support"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _service(session: Session) -> TripSupportService:
    return TripSupportService(session)


Service = Annotated[TripSupportService, Depends(_service)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "TRIP_RESOURCE_NOT_FOUND", "message": "The trip resource is unavailable."})


@router.get("/{itinerary_id}/checklists", response_model=ChecklistListResponse)
async def list_checklists(itinerary_id: str, claims: CurrentConsumer, service: Service) -> ChecklistListResponse:
    items = await service.list_checklist(itinerary_id, claims.user_id)
    if items is None:
        raise _not_found()
    return ChecklistListResponse(items=[ChecklistItemResponse.model_validate(item) for item in items])


@router.post("/{itinerary_id}/checklists", response_model=ChecklistItemResponse, status_code=status.HTTP_201_CREATED)
async def create_checklist(itinerary_id: str, body: ChecklistCreateRequest, claims: CurrentConsumer, service: Service) -> ChecklistItemResponse:
    item = await service.create_checklist(itinerary_id, claims.user_id, **body.model_dump())
    if item is None:
        raise _not_found()
    return ChecklistItemResponse.model_validate(item)


@router.patch("/{itinerary_id}/checklists/{item_id}", response_model=ChecklistItemResponse)
async def update_checklist(itinerary_id: str, item_id: str, body: ChecklistUpdateRequest, claims: CurrentConsumer, service: Service) -> ChecklistItemResponse:
    item = await service.update_checklist(item_id, claims.user_id, **body.model_dump(exclude_unset=True))
    if item is None:
        raise _not_found()
    return ChecklistItemResponse.model_validate(item)


@router.delete("/{itinerary_id}/checklists/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_checklist(itinerary_id: str, item_id: str, claims: CurrentConsumer, service: Service) -> None:
    if await service.delete_checklist(item_id, claims.user_id) is None:
        raise _not_found()


@router.get("/{itinerary_id}/budgets", response_model=BudgetListResponse)
async def list_budgets(itinerary_id: str, claims: CurrentConsumer, service: Service) -> BudgetListResponse:
    result = await service.list_budget(itinerary_id, claims.user_id)
    if result is None:
        raise _not_found()
    items, totals = result
    return BudgetListResponse(
        items=[BudgetItemResponse.model_validate(item) for item in items],
        totals=[BudgetTotalResponse(currency=currency, total_amount=amount) for currency, amount in totals],
    )


@router.post("/{itinerary_id}/budgets", response_model=BudgetItemResponse, status_code=status.HTTP_201_CREATED)
async def create_budget(itinerary_id: str, body: BudgetCreateRequest, claims: CurrentConsumer, service: Service) -> BudgetItemResponse:
    item = await service.create_budget(itinerary_id, claims.user_id, **body.model_dump())
    if item is None:
        raise _not_found()
    return BudgetItemResponse.model_validate(item)


@router.patch("/{itinerary_id}/budgets/{item_id}", response_model=BudgetItemResponse)
async def update_budget(itinerary_id: str, item_id: str, body: BudgetUpdateRequest, claims: CurrentConsumer, service: Service) -> BudgetItemResponse:
    item = await service.update_budget(item_id, claims.user_id, **body.model_dump(exclude_unset=True))
    if item is None:
        raise _not_found()
    return BudgetItemResponse.model_validate(item)


@router.delete("/{itinerary_id}/budgets/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(itinerary_id: str, item_id: str, claims: CurrentConsumer, service: Service) -> None:
    if await service.delete_budget(item_id, claims.user_id) is None:
        raise _not_found()
