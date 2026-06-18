from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from feature.search.schema import SearchNovelResponse
from feature.search.service import search_novels_by_text

router_search = APIRouter(prefix="/search", tags=["search"])

@router_search.get("/{query}", response_model=list[SearchNovelResponse])
async def search_novels(query: str, db: AsyncSession = Depends(get_db)):
    novels = await search_novels_by_text(db, query)
    if not novels:
        raise HTTPException(status_code=404, detail="No novels found matching the query")
    return novels


