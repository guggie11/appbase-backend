"""Menu schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class RoleInMenu(BaseModel):
    id: uuid.UUID
    name: str
    slug: str

    model_config = {"from_attributes": True}


class MenuResponse(BaseModel):
    id: uuid.UUID
    label: str
    icon: str | None = None
    path: str | None = None
    parent_id: uuid.UUID | None = None
    order_index: int
    is_active: bool
    roles: list[RoleInMenu] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MenuTreeResponse(BaseModel):
    id: uuid.UUID
    label: str
    icon: str | None = None
    path: str | None = None
    order_index: int
    children: list[MenuTreeResponse] = []

    model_config = {"from_attributes": True}


class CreateMenuRequest(BaseModel):
    label: str
    icon: str | None = None
    path: str | None = None
    parent_id: uuid.UUID | None = None
    order_index: int = 0
    is_active: bool = True
    role_ids: list[uuid.UUID] = []


class UpdateMenuRequest(BaseModel):
    label: str | None = None
    icon: str | None = None
    path: str | None = None
    parent_id: uuid.UUID | None = None
    order_index: int | None = None
    is_active: bool | None = None
    role_ids: list[uuid.UUID] | None = None


class UpdateMenuOrderRequest(BaseModel):
    order_index: int


class AssignMenuRolesRequest(BaseModel):
    role_ids: list[uuid.UUID]
