"""Role schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.permission import PermissionResponse


class RoleResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    is_system: bool
    is_active: bool
    # platform / built-in / custom — drives the badge and the edit lock.
    kind: str = "custom"
    # How many users hold this role; shown next to the badge.
    user_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleWithPermissionsResponse(RoleResponse):
    permissions: list[PermissionResponse] = []


class CreateRoleRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateRoleRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class AssignPermissionsRequest(BaseModel):
    permission_ids: list[uuid.UUID]
