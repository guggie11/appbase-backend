"""Auth request/response schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_policy(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password minimal 8 karakter")
        if not any(c.isupper() for c in v):
            raise ValueError("Password harus mengandung huruf besar")
        if not any(c.islower() for c in v):
            raise ValueError("Password harus mengandung huruf kecil")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password harus mengandung angka")
        if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in v):
            raise ValueError("Password harus mengandung simbol")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_policy(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password minimal 8 karakter")
        if not any(c.isupper() for c in v):
            raise ValueError("Password harus mengandung huruf besar")
        if not any(c.islower() for c in v):
            raise ValueError("Password harus mengandung huruf kecil")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password harus mengandung angka")
        if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in v):
            raise ValueError("Password harus mengandung simbol")
        return v


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    status: str
    avatar: str | None = None
    is_verified: bool
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserBriefResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    status: str

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserBriefResponse
