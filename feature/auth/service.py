import secrets
import string

import bcrypt
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import os
from database import get_db
from feature.auth.schema import TokenData
from models.user import User
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from pydantic import EmailStr




oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"))

conf = ConnectionConfig(
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "your_email@gmail.com"),
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "your_app_password"),
    MAIL_FROM = os.getenv("MAIL_FROM", "your_email@gmail.com"),
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587)),
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)




# region Password Hashing and Token Generation
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

def create_access_token(data:dict):
    to_encode = data.copy()
    
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    token = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return token

def verify_access_token(token: str, credentials_exception):
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise credentials_exception



# endregion

def create_reset_token(email: str) -> str:
    """Creates a short-lived JWT token specifically for password resets."""

    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode = {
        "sub": email, 
        "type": "password_reset", 
        "exp": expire
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_reset_token(token: str, credentials_exception) -> str:
    """Verifies the reset token and returns the email if valid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        if payload.get("type") != "password_reset":
            raise credentials_exception
        
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
        return email
    except JWTError:
        raise credentials_exception

conf = ConnectionConfig(
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "your_email@gmail.com"),
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "your_app_password"),
    MAIL_FROM = os.getenv("MAIL_FROM", "your_email@gmail.com"),
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587)),
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com"),
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)

async def send_password_reset_email(email: str, token: str):
    reset_link = f"http://localhost:4200/auth/reset/password?token={token}"
    
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #ff9800;">Khôi phục mật khẩu</h2>
            <p>Chào bạn,</p>
            <p>Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản liên kết với email này.</p>
            <p>Vui lòng click vào nút bên dưới để tạo mật khẩu mới. Link này sẽ hết hạn trong vòng 15 phút.</p>
            <a href="{reset_link}" style="display: inline-block; padding: 10px 20px; background-color: #ff9800; color: #ffffff; text-decoration: none; border-radius: 4px; font-weight: bold;">
                Đặt Lại Mật Khẩu
            </a>
            <p>Nếu nút trên không hoạt động, bạn có thể copy và dán đường link sau vào trình duyệt:</p>
            <p><a href="{reset_link}" style="color: #ff9800;">{reset_link}</a></p>
            <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
            <p style="font-size: 0.9em; color: #555;">Nếu bạn không yêu cầu việc này, vui lòng bỏ qua email này.</p>
        </body>
    </html>
    """

    message = MessageSchema(
        subject="Yêu cầu đặt lại mật khẩu",
        recipients=[email], 
        body=html_content,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    
    try:
        await fm.send_message(message)
        print(f"Password reset email successfully sent to {email}")
    except Exception as e:
        print(f"Failed to send email to {email}. Error: {e}")


def generate_secure_otp(length: int = 6) -> str:
    digits = string.digits
    otp = ''.join(secrets.choice(digits) for _ in range(length))
    return otp

async def otp_email(email: str, otp: str):
    
    html_content = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <h2 style="color: #ff9800;">kích hoạt tài khoản</h2>
            <p>Chào bạn,</p>
            <p>Chúng tôi nhận được yêu cầu kích hoạt tài khoản liên kết với email này.</p>
            <p>Vui lòng nhâp mã otp sau {otp}.</p>
            <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
            <p style="font-size: 0.9em; color: #555;">Nếu bạn không yêu cầu việc này, vui lòng bỏ qua email này.</p>
        </body>
    </html>
    """

    message = MessageSchema(
        subject="kích hoạt tài khoản",
        recipients=[email],  
        body=html_content,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    
    try:
        await fm.send_message(message)
        print(f"Activate account email successfully sent to {email}")
    except Exception as e:
        print(f"Failed to send email to {email}. Error: {e}")