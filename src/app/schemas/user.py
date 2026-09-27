"""User management schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.schemas.role import RoleResponse


class UserWithRolesResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    avatar: str | None = None
    status: str
    is_verified: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    roles: list[RoleResponse] = []

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    role_ids: list[uuid.UUID] = []


class UpdateUserRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


class UpdateUserStatusRequest(BaseModel):
    status: str  # pending|active|inactive|suspended


class AssignRolesRequest(BaseModel):
    role_ids: list[uuid.UUID]
