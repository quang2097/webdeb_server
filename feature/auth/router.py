from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, update
from feature.auth import service
from feature.user.service import require_admin, require_root_admin
from models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from .schema import ActivateAccountRequest, ForgotPasswordRequest, ResetPasswordRequest, UserSignUp
from feature.common.response import AuthRegisterResponse, TokenResponse, RootAdminResponse
from jose import jwt, JWTError

router_auth = APIRouter(prefix="/auth", tags=["auth"])


# region User Registration
@router_auth.post("/rootadmin", response_model=RootAdminResponse)
async def create_root_admin(db: AsyncSession=Depends(get_db)):
    username = "admin"
    email = "admin@example.com"
    password = "admin123456"
    
    existing_admin = (await db.execute(select(User).where(User.user_email == email))).scalar_one_or_none()
    if existing_admin:
        return {
            "message": "Root admin user already exists!",
            "user_name": existing_admin.user_name,
            "user_email": existing_admin.user_email,
            "user_id": existing_admin.user_id,
        }

    new_admin = User(
        user_name=username,
        user_email=email,
        user_hashedpassword=service.hash_password(password),
        user_role="admin",
        user_isactivated=True
    )
    
    db.add(new_admin)
    await db.commit()
    await db.refresh(new_admin)
    
    return {
        "message": "Root admin user created successfully",
        "user_name": new_admin.user_name,
        "user_email": new_admin.user_email,
        "user_id": new_admin.user_id
    }


@router_auth.put("/newadmin/{user_id}")
async def create_admin(user_id: str, current_user: User = Depends(require_root_admin), db: AsyncSession=Depends(get_db)):
    user = await db.get(User, user_id)
    if user.user_name == "admin":
        raise HTTPException(status_code=400, detail="Cannot promote an root admin")
    if user.user_role == "admin":
        raise HTTPException(status_code=400, detail="Cannot promote an admin user")
    if user.user_islocked:
        raise HTTPException(status_code=400, detail="Cannot promote an locked user")
    else:
        await db.execute(update(User).where(User.user_id == user_id).values(user_role="admin"))
        await db.commit()
    return {"message": "User promoted successfully"}

@router_auth.put("/dropadmin/{user_id}")
async def drop_admin(user_id: str, current_user: User = Depends(require_root_admin), db: AsyncSession=Depends(get_db)):
    user = await db.get(User, user_id)
    if user.user_name == "admin":
        raise HTTPException(status_code=400, detail="Cannot drop an root admin")
    if user.user_role == "user":
        raise HTTPException(status_code=400, detail="Cannot drop an user")
    else:
        await db.execute(update(User).where(User.user_id == user_id).values(user_role="user"))
        await db.commit()
    return {"message": "Admin dropped successfully"}


@router_auth.post("/signup", response_model=AuthRegisterResponse)
async def signup(user_data: UserSignUp, db: AsyncSession=Depends(get_db)):
    
    existing_username = (await db.execute(select(User).where(User.user_name == user_data.user_name))).scalar()
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already exists")

    existing_user = (await db.execute(select(User).where(User.user_email == user_data.user_email))).scalar()
    
    new_otp = service.generate_secure_otp()
    hashed_password = service.hash_password(user_data.password)
    
    if existing_user:
        if existing_user.user_isactivated:
            raise HTTPException(status_code=400, detail="Email already exists and is activated")
        else:
            existing_user.user_name = user_data.user_name
            existing_user.user_hashedpassword = hashed_password
            existing_user.otp = new_otp
            
            await db.commit()
            await service.otp_email(existing_user.user_email, new_otp)
            
            return {
                "message": "Account exists but not activated. New OTP sent.",
                "user_name": existing_user.user_name,
                "user_email": existing_user.user_email,
                "user_id": str(existing_user.user_id) 
            }
    
    new_user = User(
        user_name=user_data.user_name,
        user_email=user_data.user_email,
        user_hashedpassword=hashed_password,
        user_isactivated=False,
        otp=new_otp
    )

    db.add(new_user)
    await db.commit()
    
    await service.otp_email(new_user.user_email, new_otp)

    return {
        "message": "User created successfully. Please check email for OTP.",
        "user_name": new_user.user_name,
        "user_email": new_user.user_email,
        "user_id": str(new_user.user_id)
    }

@router_auth.put("/activate/account")
async def activateAccount(user_data: ActivateAccountRequest, db: AsyncSession=Depends(get_db)):
    user = await db.get(User, user_data.user_id)
    if user.user_islocked:
        raise HTTPException(status_code=400, detail="Cannot activate an locked user")
    if user.otp != user_data.otp:
       raise HTTPException(status_code=400, detail="Wrong otp")
    else:
        await db.execute(update(User).where(User.user_id == user_data.user_id).values(user_isactivated=True))
        await db.commit()
    return {"message": "User activated successfully"}



# region User Login


@router_auth.post("/login", description="Using email and password to login", response_model=TokenResponse)
async def login(user_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession=Depends(get_db)):
    user = (await db.execute(select(User).where(User.user_email == user_data.username))).scalar()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or password")

    if not service.verify_password(user_data.password, user.user_hashedpassword):
        raise HTTPException(status_code=400, detail="Invalid email or password")
    
    if user.user_islocked:
        raise HTTPException(status_code=403, detail="Account is locked. Please contact support.")
    
    if user.user_isactivated == False:
        raise HTTPException(status_code=403, detail="Account is not activated yet.")
    
    access_token = service.create_access_token(data={
        "user_id": str(user.user_id),
        "user_name":user.user_name,
         "user_email":user.user_email,
        "user_role":user.user_role})
    return {"access_token": access_token, "token_type": "bearer"}

# endregion 

@router_auth.get("/verify-token", description="Check if the provided access token is valid and not expired")
async def verify_token(token: str = Depends(service.oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token has expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:

        payload = service.verify_access_token(token, credentials_exception)
        
        user_email: str = payload.get("user_email")
        if user_email is None:
            raise credentials_exception
            
        return {
            "status": "valid", 
            "user_id": payload.get("user_id"),
            "user_name": payload.get("user_name"),
            "user_email": user_email,
            "user_role": payload.get("user_role")
        }
        
    except JWTError: 
        raise credentials_exception 
    
@router_auth.post("/forgot-password", description="Request a password reset link via email")
async def forgot_password(request: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.user_email == request.email))).scalar_one_or_none()
    
    if user:
        reset_token = service.create_reset_token(request.email)
        
        await service.send_password_reset_email(user.user_email, reset_token)

    return {"message": "If an account with that email exists, a password reset link has been sent."}


@router_auth.post("/reset-password", description="Submit a new password using a valid reset token")
async def reset_password(request: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired reset token"
    )
    
    email = service.verify_reset_token(request.token, credentials_exception)
    
    user = (await db.execute(select(User).where(User.user_email == email))).scalar_one_or_none()
    if not user:
        raise credentials_exception
        
    new_hashed_password = service.hash_password(request.new_password)
    user.user_hashedpassword = new_hashed_password
    
    await db.commit()
    
    return {"message": "Password has been reset successfully."}

# endregion
