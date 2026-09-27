"""Audit log schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    action: str
    module: str
    entity_id: str | None = None
    ip_address: str | None = None
    request_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
