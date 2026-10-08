"""Category schemas.

Note what Update does not accept: `code`. It is the key other tables
reference, so allowing an edit would break them silently.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CategoryGroupResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_system: bool
    is_active: bool
    # How many items it holds; shown on the group card.
    category_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateCategoryGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Derived from the name when omitted.
    code: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    icon: str | None = None
    color: str | None = None


class UpdateCategoryGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    icon: str | None = None
    color: str | None = None
    is_active: bool | None = None


class CategoryResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    code: str
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    order_index: int
    is_system: bool
    status: str
    deprecated_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CategoryTreeNode(CategoryResponse):
    children: list["CategoryTreeNode"] = []


class CreateCategoryRequest(BaseModel):
    group_id: uuid.UUID
    name: str = Field(min_length=1, max_length=150)
    code: str | None = Field(default=None, max_length=100)
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=300)
    icon: str | None = None
    color: str | None = None
    order_index: int = 0


class UpdateCategoryRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=300)
    icon: str | None = None
    color: str | None = None
    order_index: int | None = None


class DeprecateCategoryRequest(BaseModel):
    # Required: "why was this switched off" is the first question later.
    reason: str = Field(min_length=1, max_length=500)
