from sqlalchemy import update
from uuid import UUID
from models.novel import Novel
from sqlalchemy.ext.asyncio import AsyncSession


async def increase_novel_views(db: AsyncSession, novel_id: UUID) -> None:
    await db.execute(
        update(Novel)
        .where(Novel.novel_id == novel_id)
        .values(novel_views=Novel.novel_views + 1)
    )
    print(f"Novel {novel_id} views increased")
    await db.commit()


async def increase_novel_downloads(db: AsyncSession, novel_id: UUID) -> None:
    await db.execute(
        update(Novel)
        .where(Novel.novel_id == novel_id)
        .values(novel_downloads=Novel.novel_downloads + 1)
    )
    print(f"Novel {novel_id} downloads increased")
    await db.commit()