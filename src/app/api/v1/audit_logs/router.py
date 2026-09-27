"""Audit logs API router."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.audit_logs import service
from app.schemas.audit_log import AuditLogResponse
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("/", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    user_id: uuid.UUID | None = Query(default=None),
    module: str | None = Query(default=None),
    action: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("audit.read")),
):
    items, total = await service.list_audit_logs(
        db,
        user_id=user_id,
        module=module,
        action=action,
        date_from=date_from,
        date_to=date_to,
        page=page,
        per_page=per_page,
    )
    data = [AuditLogResponse(**item) for item in items]
    return PaginatedResponse(data=data, total=total, page=page, per_page=per_page, message="Berhasil")
