

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.novel import Novel


async def search_novels_by_text(db: AsyncSession, query: str, limit: int | None = None) -> list[Novel]:
    title_stmt = select(Novel).where(Novel.novel_title.ilike(f"%{query}%"))
    if limit is not None:
        title_stmt = title_stmt.limit(limit)

    result = await db.execute(title_stmt)
    novels = result.scalars().all()

    if novels:
        return novels

    author_stmt = select(Novel).where(Novel.novel_author.ilike(f"%{query}%"))
    if limit is not None:
        author_stmt = author_stmt.limit(limit)

    result = await db.execute(author_stmt)
    return result.scalars().all()




