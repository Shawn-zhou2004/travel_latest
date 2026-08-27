from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.modules.community.schemas import PostResponse
from app.modules.search.service import SearchService, SearchUnavailableError


router = APIRouter(prefix="/search", tags=["search"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/posts")
async def search_posts(session: Session, query: str | None = None, city_code: str | None = None) -> dict[str, object]:
    try:
        result = await SearchService(session).search_posts(query, city_code)
    except SearchUnavailableError as error:
        raise HTTPException(503, detail={"code": error.code, "message": str(error)}) from error
    return {"source": result.source, "items": [PostResponse.model_validate(item).model_dump(mode="json") for item in result.items]}
