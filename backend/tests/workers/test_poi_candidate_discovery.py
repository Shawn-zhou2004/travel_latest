from datetime import date
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.modules.ai_workflows.models import GenerationJob
from app.modules.admin.models import PoiCandidate
from app.modules.maps.service import MapPOI
from app.workers import domain_handlers


@pytest.mark.anyio
async def test_confirmed_preview_discovery_creates_and_updates_pending_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        job = GenerationJob(user_id=str(uuid.uuid4()), idempotency_key="discover-poi", city_code="460200", prompt="Sanya", start_date=date(2026, 8, 11), end_date=date(2026, 8, 11), request_json={})
        session.add(job)
        await session.commit()

        class Maps:
            async def verify_poi(self, poi_id: str) -> MapPOI:
                return MapPOI(poi_id, "天涯海角游览区", "三亚市", (109.2, 18.3), type_name="风景名胜", adcode="460204")

        monkeypatch.setattr(domain_handlers, "AMapService", Maps)
        event = {"payload": {"generation_job_id": job.id, "poi_ids": ["poi-1", "poi-1"]}}
        await domain_handlers._record_confirmed_preview_poi_candidates(session, event)
        await session.commit()
        candidate = await session.scalar(__import__("sqlalchemy").select(PoiCandidate).where(PoiCandidate.poi_id == "poi-1"))
        assert candidate is not None
        assert (candidate.status, candidate.city_code, candidate.discovery_count, candidate.confirmed_itinerary_count) == ("pending_review", "460200", 1, 1)
        await domain_handlers._record_confirmed_preview_poi_candidates(session, event)
        await session.commit()
        await session.refresh(candidate)
        assert (candidate.discovery_count, candidate.confirmed_itinerary_count) == (2, 2)
    await engine.dispose()
