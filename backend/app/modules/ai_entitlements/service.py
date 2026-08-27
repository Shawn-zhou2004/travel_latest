from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utc_now
from app.models.user import User
from app.modules.membership_purchases.models import AIQuotaPeriod


Capability = Literal["itinerary_generation", "assistant_message"]
QuotaSource = Literal["free", "membership"]


@dataclass(frozen=True)
class AIEntitlementConsumption:
    source: QuotaSource
    remaining: int
    period_end: datetime
    _period_id: str
    _capability: Capability


@dataclass(frozen=True)
class AIEntitlementBalance:
    source: QuotaSource
    itinerary_generation_remaining: int
    assistant_message_remaining: int
    period_end: datetime


class AIEntitlementError(Exception):
    def __init__(self, *, source: QuotaSource, period_end: datetime) -> None:
        self.code = "AI_QUOTA_EXHAUSTED"
        self.message = "The AI quota for this period is exhausted."
        self.status_code = 429
        self.source = source
        self.period_end = period_end
        self.upgrade_available = source == "free"
        super().__init__(self.code)


class AIEntitlementService:
    _FREE_GENERATION_LIMIT = 1
    _FREE_ASSISTANT_LIMIT = 20

    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self.session = session
        self._now = now

    def _current_time(self) -> datetime:
        value = self._now or utc_now()
        return value.astimezone(UTC)

    @staticmethod
    def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
        start = datetime(now.year, now.month, 1, tzinfo=UTC)
        if now.month == 12:
            end = datetime(now.year + 1, 1, 1, tzinfo=UTC)
        else:
            end = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
        return start, end

    @staticmethod
    def _columns(capability: Capability) -> tuple[str, str]:
        if capability == "itinerary_generation":
            return "generation_used", "generation_limit"
        return "assistant_used", "assistant_limit"

    async def consume(self, user_id: str, capability: Capability) -> AIEntitlementConsumption:
        now = self._current_time()
        # The user row serializes creation of the nullable free-period row as well as consumption.
        await self.session.scalar(select(User.id).where(User.id == user_id).with_for_update())
        period = await self._active_membership_period(user_id, now)
        source: QuotaSource = "membership"
        if period is None:
            source = "free"
            period = await self._free_period(user_id, now)
        used_name, limit_name = self._columns(capability)
        used = getattr(period, used_name)
        limit = getattr(period, limit_name)
        if used >= limit:
            raise AIEntitlementError(source=source, period_end=period.period_end)
        setattr(period, used_name, used + 1)
        await self.session.flush()
        return AIEntitlementConsumption(source, limit - used - 1, period.period_end, period.id, capability)

    async def release(self, consumption: AIEntitlementConsumption) -> None:
        period = await self.session.scalar(
            select(AIQuotaPeriod).where(AIQuotaPeriod.id == consumption._period_id).with_for_update()
        )
        if period is None:
            return
        used_name, _ = self._columns(consumption._capability)
        used = getattr(period, used_name)
        if used > 0:
            setattr(period, used_name, used - 1)
            await self.session.flush()

    async def balances(self, user_id: str) -> tuple[AIEntitlementBalance, AIEntitlementBalance | None]:
        now = self._current_time()
        start, end = self._month_bounds(now)
        free = await self.session.scalar(select(AIQuotaPeriod).where(
            AIQuotaPeriod.user_id == user_id,
            AIQuotaPeriod.source_type == "free",
            AIQuotaPeriod.period_start == start,
            AIQuotaPeriod.period_end == end,
        ))
        free_balance = AIEntitlementBalance(
            "free",
            self._FREE_GENERATION_LIMIT - (free.generation_used if free else 0),
            self._FREE_ASSISTANT_LIMIT - (free.assistant_used if free else 0),
            end,
        )
        membership = await self._active_membership_period(user_id, now, lock=False)
        if membership is None:
            return free_balance, None
        return free_balance, AIEntitlementBalance(
            "membership",
            membership.generation_limit - membership.generation_used,
            membership.assistant_limit - membership.assistant_used,
            membership.period_end,
        )

    async def _active_membership_period(
        self, user_id: str, now: datetime, *, lock: bool = True
    ) -> AIQuotaPeriod | None:
        statement = select(AIQuotaPeriod).where(
            AIQuotaPeriod.user_id == user_id,
            AIQuotaPeriod.source_type == "membership_purchase",
            AIQuotaPeriod.period_start <= now,
            AIQuotaPeriod.period_end > now,
        ).order_by(AIQuotaPeriod.period_end.desc()).limit(1)
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def _free_period(self, user_id: str, now: datetime) -> AIQuotaPeriod:
        start, end = self._month_bounds(now)
        period = await self.session.scalar(select(AIQuotaPeriod).where(
            AIQuotaPeriod.user_id == user_id,
            AIQuotaPeriod.source_type == "free",
            AIQuotaPeriod.period_start == start,
            AIQuotaPeriod.period_end == end,
        ).with_for_update())
        if period is not None:
            return period
        period = AIQuotaPeriod(
            user_id=user_id,
            source_type="free",
            period_start=start,
            period_end=end,
            generation_limit=self._FREE_GENERATION_LIMIT,
            assistant_limit=self._FREE_ASSISTANT_LIMIT,
        )
        self.session.add(period)
        await self.session.flush()
        return period
