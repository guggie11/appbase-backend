"""Permissions API router."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.seed import MATRIX_ACTIONS, matrix_rows
from app.models.rbac import Permission
from app.schemas.common import SuccessResponse
from app.schemas.permission import PermissionResponse

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/matrix", response_model=SuccessResponse[dict])
async def permission_matrix(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("permissions.read")),
):
    """The RESOURCE x ACTION grid behind the Roles & Permissions screen.

    Built from the live catalogue rather than a hardcoded list, so a module
    added later shows up without touching the frontend.
    """
    rows = (
        await db.execute(select(Permission).order_by(Permission.module, Permission.action))
    ).scalars().all()

    catalogue = [
        {"slug": p.slug, "module": p.module, "action": p.action, "name": p.name}
        for p in rows
    ]
    meta = {p.slug: p for p in rows}

    grid = matrix_rows(catalogue)
    for row in grid:
        for cell in row["cells"].values():
            perm = meta.get(cell["slug"]) if cell["slug"] else None
            cell["name"] = perm.name if perm else None
            cell["id"] = str(perm.id) if perm else None
            cell["is_dangerous"] = bool(perm.is_dangerous) if perm else False
            cell["description"] = perm.description if perm else None

    return SuccessResponse(data={"actions": MATRIX_ACTIONS, "rows": grid})


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
