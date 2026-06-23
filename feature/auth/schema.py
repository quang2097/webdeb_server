from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator
import re


class UserSignUp(BaseModel):
    user_name: str
    password: str = Field(
        ..., 
        min_length=8, 
        max_length=128, 
        description="Password must be between 8 and 128 characters, and include at least one letter and one number."
    )
    user_email: EmailStr

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value):
            raise ValueError("Mật khẩu phải chứa ít nhất một chữ cái.")
        
        if not re.search(r"\d", value):
            raise ValueError("Mật khẩu phải chứa ít nhất một chữ số.")
        
        if " " in value:
            raise ValueError("Mật khẩu không được chứa khoảng trắng.")
            
        return value
    
class ActivateAccountRequest(BaseModel):
    user_id: str  
    otp: str     

class Token(BaseModel):
    access_token: str
    token_type: str
    
class TokenData(BaseModel):
    user_id : Optional[int] = None
    user_name: str | None = None
    user_email: str | None = None
    user_role: str | None = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(
        ..., 
        min_length=8, 
        max_length=128, 
        description="Password must be between 8 and 128 characters, and include at least one letter and one number."
    )

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value):
            raise ValueError("Mật khẩu phải chứa ít nhất một chữ cái.")
        if not re.search(r"\d", value):
            raise ValueError("Mật khẩu phải chứa ít nhất một chữ số.")
        if " " in value:
            raise ValueError("Mật khẩu không được chứa khoảng trắng.")
        return value
    