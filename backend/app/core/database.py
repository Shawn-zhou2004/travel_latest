import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import Settings


def _database_url() -> str:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured

    try:
        mysql_dsn = Settings().mysql_dsn
    except ValueError:
        mysql_dsn = None

    if mysql_dsn:
        return mysql_dsn.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
    return "sqlite+aiosqlite:///:memory:"


DATABASE_URL = _database_url()

# Engine construction is lazy: no database connection is made until a session is used.
engine = create_async_engine(DATABASE_URL)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
