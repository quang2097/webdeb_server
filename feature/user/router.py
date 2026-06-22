from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from feature.auth.service import hash_password
from feature.user.service import get_current_user
from models.novel import Novel
from models.user import User
from database import get_db
from feature.user.schema import UserUpdate
from feature.common.response import MessageResponse, UserAvatarResponse, UserMeResponse, UserProfileResponse

router_user = APIRouter(prefix="/user", tags=["user"])

# region check current user
@router_user.get("/me", response_model=UserMeResponse)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return {"user_name": current_user.user_name,
            "user_email": current_user.user_email,
            "user_id": current_user.user_id,
            "user_role": current_user.user_role}
    

@router_user.put("/me", response_model=MessageResponse)
async def update_current_user(user_data: UserUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    update_data = user_data.model_dump(exclude_unset=True)

    if(current_user.user_name=="admin"):
        raise HTTPException(status_code=405, detail="this userr is root admin")

    if "user_email" in update_data and update_data["user_email"] != current_user.user_email:
        existing_email = (
            await db.execute(select(User).where(User.user_email == update_data["user_email"]))
        ).scalar_one_or_none()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")

    if "user_name" in update_data and update_data["user_name"] != current_user.user_name:
        existing_username = (
            await db.execute(select(User).where(User.user_name == update_data["user_name"]))
        ).scalar_one_or_none()
        if existing_username:
            raise HTTPException(status_code=400, detail="Username already exists")

    for key, value in update_data.items():
        if key == "password":
            current_user.user_hashedpassword = hash_password(value)
            continue
        if hasattr(current_user, key):
            setattr(current_user, key, value)
    await db.commit()
    return {"message": "User updated successfully"}



# endregion


# region user information
@router_user.get("/avatar/{user_id}/novels", response_model=UserAvatarResponse)
async def get_user_avatar_and_name(user_id: UUID, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_name": user.user_name,
            "user_avatar": user.user_avatarurl}

@router_user.get("/{user_id}", response_model=UserProfileResponse)
async def read_user_info(user_id: UUID,db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_novels = await db.execute(select(Novel).where(Novel.novel_user == user_id))
    return {"user_name": user.user_name,
            "user_email": user.user_email,
            "user_id": user.user_id,
            "user_role": user.user_role,
            "user_novels": [novel for novel in user_novels.scalars()]}





# endregion
