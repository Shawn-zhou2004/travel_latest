from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.itineraries.models import Itinerary, TripCollaborator
from app.modules.trip_support.models import BudgetItem, ChecklistItem


class TripSupportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_checklist(self, itinerary_id: str, actor_id: str) -> list[ChecklistItem] | None:
        if not await self._can_read(itinerary_id, actor_id):
            return None
        return list((await self.session.scalars(
            select(ChecklistItem).where(ChecklistItem.itinerary_id == itinerary_id).order_by(ChecklistItem.category, ChecklistItem.created_at)
        )).all())

    async def create_checklist(self, itinerary_id: str, actor_id: str, **values: str) -> ChecklistItem | None:
        if not await self._can_edit(itinerary_id, actor_id):
            return None
        item = ChecklistItem(itinerary_id=itinerary_id, **values)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update_checklist(self, item_id: str, actor_id: str, **values: object) -> ChecklistItem | None:
        item = await self.session.get(ChecklistItem, item_id)
        if item is None or not await self._can_edit(item.itinerary_id, actor_id):
            return None
        for field, value in values.items():
            setattr(item, field, value)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete_checklist(self, item_id: str, actor_id: str) -> bool | None:
        item = await self.session.get(ChecklistItem, item_id)
        if item is None or not await self._can_edit(item.itinerary_id, actor_id):
            return None
        await self.session.delete(item)
        await self.session.commit()
        return True

    async def list_budget(self, itinerary_id: str, actor_id: str) -> tuple[list[BudgetItem], list[tuple[str, Decimal]]] | None:
        if not await self._can_read(itinerary_id, actor_id):
            return None
        items = list((await self.session.scalars(
            select(BudgetItem).where(BudgetItem.itinerary_id == itinerary_id).order_by(BudgetItem.category, BudgetItem.created_at)
        )).all())
        totals = list((await self.session.execute(
            select(BudgetItem.currency, func.coalesce(func.sum(BudgetItem.amount), 0))
            .where(BudgetItem.itinerary_id == itinerary_id).group_by(BudgetItem.currency).order_by(BudgetItem.currency)
        )).all())
        return items, [(currency, Decimal(total)) for currency, total in totals]

    async def create_budget(self, itinerary_id: str, actor_id: str, **values: object) -> BudgetItem | None:
        if not await self._can_edit(itinerary_id, actor_id):
            return None
        item = BudgetItem(itinerary_id=itinerary_id, **values)
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def update_budget(self, item_id: str, actor_id: str, **values: object) -> BudgetItem | None:
        item = await self.session.get(BudgetItem, item_id)
        if item is None or not await self._can_edit(item.itinerary_id, actor_id):
            return None
        for field, value in values.items():
            setattr(item, field, value)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def delete_budget(self, item_id: str, actor_id: str) -> bool | None:
        item = await self.session.get(BudgetItem, item_id)
        if item is None or not await self._can_edit(item.itinerary_id, actor_id):
            return None
        await self.session.delete(item)
        await self.session.commit()
        return True

    async def _can_read(self, itinerary_id: str, actor_id: str) -> bool:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None:
            return False
        if itinerary.owner_id == actor_id:
            return True
        return await self.session.scalar(select(TripCollaborator.id).where(
            TripCollaborator.itinerary_id == itinerary_id,
            TripCollaborator.user_id == actor_id,
            TripCollaborator.status == "accepted",
        )) is not None

    async def _can_edit(self, itinerary_id: str, actor_id: str) -> bool:
        itinerary = await self.session.get(Itinerary, itinerary_id)
        if itinerary is None:
            return False
        if itinerary.owner_id == actor_id:
            return True
        return await self.session.scalar(select(TripCollaborator.id).where(
            TripCollaborator.itinerary_id == itinerary_id,
            TripCollaborator.user_id == actor_id,
            TripCollaborator.role == "editor",
            TripCollaborator.status == "accepted",
        )) is not None
