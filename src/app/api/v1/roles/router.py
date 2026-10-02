"""Roles API router."""
import contextlib
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.roles import service
from app.core.audit import log_action
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.permission import PermissionResponse
from app.schemas.role import (
    AssignPermissionsRequest,
    CreateRoleRequest,
    RoleResponse,
    UpdateRoleRequest,
)

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("/", response_model=PaginatedResponse[RoleResponse])
async def list_roles(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=100),
    is_active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("roles.read")),
):
    roles, total = await service.list_roles(db, page=page, per_page=per_page, is_active=is_active)
    return PaginatedResponse(
        data=roles,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{role_id}", response_model=SuccessResponse[RoleResponse])
async def get_role(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("roles.read")),
):
    role = await service.get_role(db, role_id)
    return SuccessResponse(data=RoleResponse.model_validate(role), message="Berhasil")


@router.post("/", response_model=SuccessResponse[RoleResponse], status_code=201)
async def create_role(
    body: CreateRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("roles.create")),
):
    role = await service.create_role(db, name=body.name, description=body.description)
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="create", module="roles", entity_id=str(role.id), new_value={"name": role.name}, request=request)
        await db.commit()
    return SuccessResponse(data=RoleResponse.model_validate(role), message="Role berhasil dibuat")


@router.put("/{role_id}", response_model=SuccessResponse[RoleResponse])
async def update_role(
    role_id: uuid.UUID,
    body: UpdateRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("roles.update")),
):
    role = await service.update_role(
        db, role_id, name=body.name, description=body.description, is_active=body.is_active
    )
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="update", module="roles", entity_id=str(role_id), new_value={"name": body.name, "is_active": body.is_active}, request=request)
        await db.commit()
    return SuccessResponse(data=RoleResponse.model_validate(role), message="Role berhasil diperbarui")


@router.post("/{role_id}/duplicate", response_model=SuccessResponse[RoleResponse])
async def duplicate_role(
    role_id: uuid.UUID,
    body: CreateRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("roles.create")),
):
    role = await service.duplicate_role(db, role_id, name=body.name)
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="create", module="roles", entity_id=str(role.id), new_value={"name": role.name, "duplicated_from": str(role_id)}, request=request)
        await db.commit()
    return SuccessResponse(data=RoleResponse.model_validate(role), message="Role berhasil diduplikasi")


@router.delete("/{role_id}", response_model=SuccessResponse[None])
async def delete_role(
    role_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("roles.delete")),
):
    await service.delete_role(db, role_id)
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="delete", module="roles", entity_id=str(role_id), request=request)
        await db.commit()
    return SuccessResponse(data=None, message="Role berhasil dihapus")


@router.get("/{role_id}/permissions", response_model=SuccessResponse[list[PermissionResponse]])
async def get_role_permissions(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("roles.read")),
):
    permissions = await service.get_role_permissions(db, role_id)
    return SuccessResponse(data=permissions, message="Berhasil")


@router.put("/{role_id}/permissions", response_model=SuccessResponse[list[PermissionResponse]])
async def assign_permissions(
    role_id: uuid.UUID,
    body: AssignPermissionsRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("permissions.assign")),
):
    permissions = await service.assign_permissions(db, role_id, body.permission_ids)
    return SuccessResponse(data=permissions, message="Permissions berhasil diperbarui")
