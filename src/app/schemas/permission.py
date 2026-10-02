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
    # Metadata that makes the permission matrix readable rather than a wall
    # of slugs: a plain sentence, the section it belongs to, and whether
    # ticking it is destructive.
    description: str | None = None
    group: str | None = None
    is_dangerous: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}
