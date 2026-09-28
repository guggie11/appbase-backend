"""Menu management router — S-055 CRUD + S-056 Dynamic menu."""
from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_permission
from app.api.v1.menus import service
from app.core.audit import log_action
from app.schemas.menu import (
    AssignMenuRolesRequest,
    CreateMenuRequest,
    MenuResponse,
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
                roles.append(RoleInMenu(
                    id=mr.role.id,
                    name=mr.role.name,
                    slug=mr.role.slug,
                ))
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

    tree = await service.get_my_menu(
        db=db,
        user_id=user_id,
        user_roles=role_slugs,
        is_super_admin=is_super_admin,
    )
    return {"data": tree, "message": "Berhasil"}


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
    )
    with contextlib.suppress(Exception):
        await log_action(db, user_id=current_user.get("sub"), action="create", module="menus", entity_id=str(menu.id), new_value={"label": menu.label}, request=request)
        await db.commit()
    return {"data": menu_to_response(menu), "message": "Menu berhasil dibuat"}


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
