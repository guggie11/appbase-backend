"""Permissions API router."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.models.rbac import Permission
from app.schemas.permission import PermissionResponse
from app.schemas.common import SuccessResponse

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/", response_model=SuccessResponse[list[PermissionResponse]])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("permissions.read")),
):
    result = await db.execute(select(Permission).order_by(Permission.module, Permission.action))
    permissions = result.scalars().all()
    # Wrapped like every other endpoint: the frontend reads res.data.data
    # throughout, so a bare array arrived as undefined and the permission
    # matrix silently rendered "0 / 0".
    return SuccessResponse(data=list(permissions))
