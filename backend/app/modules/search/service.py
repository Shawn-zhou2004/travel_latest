from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.community.models import Post


class SearchUnavailableError(Exception):
    code = "SEARCH_UNAVAILABLE"


@dataclass(frozen=True)
class PostSearchResult:
    source: str
    items: list[Post]


class SearchService:
    """Typed boundary for an optional projection provider; safe filters fall back to MySQL."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search_posts(self, query: str | None = None, city_code: str | None = None, *, force_es_failure: bool = False) -> PostSearchResult:
        if query and force_es_failure:
            raise SearchUnavailableError("Full-text search is temporarily unavailable.")
        statement = select(Post).where(Post.status == "published").order_by(Post.published_at.desc())
        if city_code:
            statement = statement.where(Post.city_code == city_code)
        if query:
            statement = statement.where(Post.title.contains(query))
        items = list((await self.session.scalars(statement)).all())
        return PostSearchResult(source="mysql_fallback" if force_es_failure else "mysql", items=items)
