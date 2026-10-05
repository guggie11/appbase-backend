"""Menu management router — S-055 CRUD + S-056 Dynamic menu."""
from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_permission
from app.api.v1.menus import service
from app.core.audit import log_action
from app.core.exceptions import AppException
from app.schemas.menu import (
    AssignMenuRolesRequest,
    CreateMenuRequest,
    MenuResponse,
    ReorderMenusRequest,
    RoleInMenu,
    UpdateMenuOrderRequest,
    UpdateMenuRequest,
)


def menu_to_response(menu) -> MenuResponse:
    """Convert Menu ORM object to MenuResponse with roles."""
    roles = []
    if hasattr(menu, "menu_roles") and menu.menu_roles:
        for mr in menu.menu_roles:
            if hasattr(mr, "role") and mr.role:
                roles.append(RoleInMenu.model_validate(mr.role))
    data = MenuResponse.model_validate(menu)
    data.roles = roles
    return data

router = APIRouter(prefix="/menus", tags=["menus"])


# ── S-055: CRUD ──────────────────────────────────────────────


@router.get("/", summary="List all menus")
async def list_menus(
    is_active: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("menu.read")),
):
    menus = await service.list_menus(db, is_active=is_active)
    return {"data": [menu_to_response(m) for m in menus], "message": "Berhasil"}


@router.get("/my-menu", summary="Get menu tree for current user (S-056)")
async def get_my_menu(
    preview_role: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from app.models.rbac import Role, UserRole

    user_id = current_user.get("sub")
    role_result = await db.execute(
        select(Role.slug)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .where(Role.is_active.is_(True))
    )
    role_slugs = [row[0] for row in role_result.fetchall()]
    is_super_admin = "super-admin" in role_slugs

    if preview_role:
        # "What does a holder of this role actually see?" — answered without
        # logging out. Only an admin who may read roles can ask.
        if not is_super_admin and "roles.read" not in await _permission_slugs(
            db, role_slugs
        ):
            raise AppException(
                code="MENUS_PREVIEW_FORBIDDEN",
                message="Tidak boleh melakukan preview sebagai role lain",
                status_code=403,
            )
        role_slugs = [preview_role]
        is_super_admin = preview_role == "super-admin"

    permissions = await _permission_slugs(db, role_slugs)

    tree = await service.get_my_menu(
        db=db,
        user_id=user_id,
        user_roles=role_slugs,
        is_super_admin=is_super_admin,
        permissions=permissions,
    )
    return {"data": tree, "message": "Berhasil"}


async def _permission_slugs(db: AsyncSession, role_slugs: list[str]) -> list[str]:
    """Flat permission slugs granted by the given roles."""
    from sqlalchemy import select

    from app.models.rbac import Permission, Role, RolePermission

    if not role_slugs:
        return []
    rows = await db.execute(
        select(Permission.slug)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.slug.in_(role_slugs))
        .where(Role.is_active.is_(True))
    )
    return sorted({row[0] for row in rows.fetchall()})


@router.get("/{menu_id}", summary="Get menu detail")
async def get_menu(
    menu_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("menu.read")),
):
    menu = await service.get_menu(db, menu_id)
    return {"data": menu_to_response(menu), "message": "Berhasil"}


@router.post("/", summary="Create menu", status_code=201)
async def create_menu(
    body: CreateMenuRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("menu.manage")),
):
    menu = await service.create_menu(
        db=db,
        label=body.label,
        icon=body.icon,
        path=body.path,
        parent_id=body.parent_id,
        order_index=body.order_index,
        is_active=body.is_active,
        role_ids=body.role_ids,
        required_permission=body.required_permission,
    )
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="create", module="menus", entity_id=str(menu.id), new_value={"label": menu.label}, request=request)
        await db.commit()
    return {"data": menu_to_response(menu), "message": "Menu berhasil dibuat"}


@router.put("/reorder", summary="Atomically reorder one sibling group")
async def reorder_menus(
    body: ReorderMenusRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("menu.manage")),
):
    menus = await service.reorder_siblings(
        db, parent_id=body.parent_id, menu_ids=body.menu_ids
    )
    with contextlib.suppress(Exception):
        await log_action(
            db,
            user_id=current_user.get("sub"),
            action="reorder",
            module="menus",
            entity_id=str(body.parent_id) if body.parent_id else None,
            new_value={"menu_ids": [str(m) for m in body.menu_ids]},
            request=request,
        )
        await db.commit()
    return {
        "data": [menu_to_response(m) for m in menus],
        "message": "Urutan menu berhasil diperbarui",
    }


@router.put("/{menu_id}", summary="Update menu")
async def update_menu(
    menu_id: uuid.UUID,
    body: UpdateMenuRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("menu.manage")),
):
    menu = await service.update_menu(
        db=db,
        menu_id=menu_id,
        label=body.label,
        icon=body.icon,
        path=body.path,
        parent_id=body.parent_id,
        order_index=body.order_index,
        is_active=body.is_active,
        role_ids=body.role_ids,
        required_permission=body.required_permission,
    )
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="update", module="menus", entity_id=str(menu_id), new_value={"label": body.label}, request=request)
        await db.commit()
    return {"data": menu_to_response(menu), "message": "Menu berhasil diperbarui"}


@router.delete("/{menu_id}", summary="Delete menu (cascade children)", status_code=200)
async def delete_menu(
    menu_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("menu.manage")),
):
    await service.delete_menu(db, menu_id)
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="delete", module="menus", entity_id=str(menu_id), request=request)
        await db.commit()
    return {"data": None, "message": "Menu berhasil dihapus"}


@router.put("/{menu_id}/order", summary="Update menu order_index")
async def update_menu_order(
    menu_id: uuid.UUID,
    body: UpdateMenuOrderRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("menu.manage")),
):
    menu = await service.update_menu_order(db, menu_id, body.order_index)
    return {"data": menu_to_response(menu), "message": "Urutan menu berhasil diperbarui"}


@router.put("/{menu_id}/roles", summary="Assign roles to menu")
async def assign_menu_roles(
    menu_id: uuid.UUID,
    body: AssignMenuRolesRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("menu.manage")),
):
    menu = await service.assign_menu_roles(db, menu_id, body.role_ids)
    return {"data": menu_to_response(menu), "message": "Role menu berhasil diperbarui"}
