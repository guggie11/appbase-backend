"""Profile-related schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    avatar: str | None = None
    status: str
    is_verified: bool
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class SessionResponse(BaseModel):
    id: uuid.UUID
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False

    model_config = {"from_attributes": True}
