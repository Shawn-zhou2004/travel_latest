import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.suppliers.client import SupplierSearchRequest, UnavailableSupplierAdapter
from app.models.base import Base
from app.models.user import User
from app.modules.orders.services import SearchService


def test_unconfigured_supplier_returns_explicit_empty_job() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(phone="13700000000")
            session.add(user)
            await session.flush()
            request = SupplierSearchRequest(search_type="hotel", origin="Hangzhou", destination="Shanghai", depart_date=date(2026, 10, 1), passenger_count=1)
            job = await SearchService(session, UnavailableSupplierAdapter()).create(user.id, "search-key", request)
            assert job.status == "empty"
            assert job.unavailable_code == "SUPPLIER_UNAVAILABLE"
            assert job.source == "supplier_unavailable"
        await engine.dispose()
    asyncio.run(scenario())
