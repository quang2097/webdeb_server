from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy import text, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from feature.user.service import require_admin
from database import SessionLocal, get_db
from models.user import User
from feature.common.response import MessageResponse, PaginatedAdminUsersResponse


router_admin = APIRouter(prefix="/admin", tags=["admin"])

@router_admin.put("/user/{user_id}/lock", response_model=MessageResponse)
async def lock_user(user_id: str, current_user = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if user.user_role == "admin":
        raise HTTPException(status_code=400, detail="Cannot lock an admin user")
    if user.user_islocked:
        raise HTTPException(status_code=400, detail="User is already locked")
    else:
        await db.execute(update(User).where(User.user_id == user_id).values(user_islocked=True))
        await db.commit()
    return {"message": "User locked successfully"}

@router_admin.put("/user/{user_id}/unlock", response_model=MessageResponse)
async def unlock_user(user_id: str, current_user = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if user.user_role == "admin":
        raise HTTPException(status_code=400, detail="Cannot unlock an admin user")
    await db.execute(update(User).where(User.user_id == user_id).values(user_islocked=False))
    await db.commit()
    return {"message": "User unlocked successfully"}

@router_admin.delete("/user/{user_id}", response_model=MessageResponse)
async def delete_user(user_id: str, current_user = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if user.user_name == "admin":
        raise HTTPException(status_code=400, detail="Cannot delete an admin user")
    await db.execute(text("DELETE FROM users WHERE user_id = :user_id"), {"user_id": user_id})
    await db.commit()
    return {"message": "User deleted successfully"}
from fastapi import Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

@router_admin.get("/users", response_model=PaginatedAdminUsersResponse)
async def get_all_users(
    current_user = Depends(require_admin), 
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
    
):
    size = 10

    offset_value = (page - 1) * size

    count_query = select(func.count()).select_from(User)
    total_items = await db.scalar(count_query) or 0

    query = select(User).offset(offset_value).limit(size)
    result = await db.execute(query)
    users = result.scalars().all()
    
    total_pages = (total_items + size - 1) // size if total_items > 0 else 0

    return {
        "users": users,
        "page": page,
        "size": size,
        "total_items": total_items,
        "total_pages": total_pages
    }