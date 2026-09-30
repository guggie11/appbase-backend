"""App settings schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class SettingResponse(BaseModel):
    id: uuid.UUID
    key: str
    value: str | None = None
    type: str
    is_public: bool
    is_secret: bool
    updated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicSettingResponse(BaseModel):
    key: str
    value: str | None = None
    type: str


class UpdateSettingRequest(BaseModel):
    value: str | None = None
