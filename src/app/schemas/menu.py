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
    # Permission slug required to see this item; NULL keeps it public.
    required_permission: str | None = None
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
    # Permission slug required to see this item; NULL keeps it public.
    required_permission: str | None = None
    role_ids: list[uuid.UUID] = []


class UpdateMenuRequest(BaseModel):
    label: str | None = None
    icon: str | None = None
    path: str | None = None
    parent_id: uuid.UUID | None = None
    order_index: int | None = None
    is_active: bool | None = None
    # Permission slug required to see this item; NULL keeps it public.
    required_permission: str | None = None
    role_ids: list[uuid.UUID] | None = None


class UpdateMenuOrderRequest(BaseModel):
    order_index: int


class ReorderMenusRequest(BaseModel):
    """Complete ordered sibling set for one parent group."""

    parent_id: uuid.UUID | None = None
    menu_ids: list[uuid.UUID]


class AssignMenuRolesRequest(BaseModel):
    role_ids: list[uuid.UUID]
