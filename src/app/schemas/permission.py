"""Permission schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class PermissionResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    module: str
    action: str
    created_at: datetime

    model_config = {"from_attributes": True}
