"""Menu management business logic service."""
from __future__ import annotations

import contextlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.core.redis import redis_client
from app.models.menu import Menu, MenuRole
from app.models.rbac import Role


async def _get_menu_or_404(db: AsyncSession, menu_id: uuid.UUID) -> Menu:
    result = await db.execute(
        select(Menu)
        .options(selectinload(Menu.menu_roles))
        .where(Menu.id == menu_id)
    )
    menu = result.scalar_one_or_none()
    if not menu:
        raise AppException(code="MENUS_NOT_FOUND", message="Menu tidak ditemukan", status_code=404)
    return menu


async def _get_depth(db: AsyncSession, parent_id: uuid.UUID) -> int:
    """Return the depth level of a parent node (root = 0)."""
    depth = 0
    current_id: uuid.UUID | None = parent_id
    visited: set[uuid.UUID] = set()
    while current_id is not None:
        if current_id in visited:
            # cycle detected while computing depth
            break
        visited.add(current_id)
        result = await db.execute(select(Menu.parent_id).where(Menu.id == current_id))
        row = result.scalar_one_or_none()
        if row is None:
            break
        current_id = row
        depth += 1
    return depth


async def _check_cycle(db: AsyncSession, menu_id: uuid.UUID, new_parent_id: uuid.UUID) -> None:
    """Raise if setting new_parent_id as parent of menu_id would create a cycle."""
    current_id: uuid.UUID | None = new_parent_id
    visited: set[uuid.UUID] = {menu_id}
    while current_id is not None:
        if current_id in visited:
            raise AppException(
                code="MENUS_CYCLE_DETECTED",
                message="Parent yang dipilih akan menyebabkan cycle pada tree menu",
                status_code=422,
            )
        visited.add(current_id)
        result = await db.execute(select(Menu.parent_id).where(Menu.id == current_id))
        row = result.scalar_one_or_none()
        current_id = row


async def _invalidate_menu_cache() -> None:
    """Invalidate all menu_user:* cache keys."""
    with contextlib.suppress(Exception):
        # Use scan to find and delete all menu_user:* keys
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor, match="menu_user:*", count=100)
            if keys:
                await redis_client.delete(*keys)
            if cursor == 0:
                break


async def list_menus(
    db: AsyncSession,
    is_active: bool | None = None,
) -> list[Menu]:
    query = select(Menu).options(selectinload(Menu.menu_roles).selectinload(MenuRole.role))
    if is_active is not None:
        query = query.where(Menu.is_active == is_active)
    query = query.order_by(Menu.order_index)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_menu(db: AsyncSession, menu_id: uuid.UUID) -> Menu:
    return await _get_menu_or_404(db, menu_id)


async def create_menu(
    db: AsyncSession,
    label: str,
    icon: str | None,
    path: str | None,
    parent_id: uuid.UUID | None,
    order_index: int,
    is_active: bool,
    role_ids: list[uuid.UUID],
) -> Menu:
    # Validate parent depth
    if parent_id is not None:
        parent_result = await db.execute(select(Menu.id).where(Menu.id == parent_id))
        if parent_result.scalar_one_or_none() is None:
            raise AppException(code="MENUS_NOT_FOUND", message="Parent menu tidak ditemukan", status_code=404)
        depth = await _get_depth(db, parent_id)
        # depth of parent + 1 for new child. Max 3 levels (0-based): root=0, child=1, grandchild=2
        # So new child depth = depth + 1 must be <= 2 (0-indexed), meaning parent depth <= 1
        if depth + 1 >= 3:
            raise AppException(
                code="MENUS_MAX_DEPTH_EXCEEDED",
                message="Kedalaman menu maksimal 3 level",
                status_code=422,
            )

    menu = Menu(
        label=label,
        icon=icon,
        path=path,
        parent_id=parent_id,
        order_index=order_index,
        is_active=is_active,
    )
    db.add(menu)
    await db.flush()

    # Assign roles
    if role_ids:
        for role_id in role_ids:
            menu_role = MenuRole(menu_id=menu.id, role_id=role_id)
            db.add(menu_role)

    await db.commit()
    await db.refresh(menu)
    await _invalidate_menu_cache()
    return menu


async def update_menu(
    db: AsyncSession,
    menu_id: uuid.UUID,
    label: str | None,
    icon: str | None,
    path: str | None,
    parent_id: uuid.UUID | None,
    order_index: int | None,
    is_active: bool | None,
    role_ids: list[uuid.UUID] | None,
) -> Menu:
    menu = await _get_menu_or_404(db, menu_id)

    if parent_id is not None and parent_id != menu.parent_id:
        if parent_id == menu_id:
            raise AppException(
                code="MENUS_CYCLE_DETECTED",
                message="Menu tidak bisa menjadi parent dirinya sendiri",
                status_code=422,
            )
        parent_result = await db.execute(select(Menu.id).where(Menu.id == parent_id))
        if parent_result.scalar_one_or_none() is None:
            raise AppException(code="MENUS_NOT_FOUND", message="Parent menu tidak ditemukan", status_code=404)
        await _check_cycle(db, menu_id, parent_id)
        depth = await _get_depth(db, parent_id)
        if depth + 1 >= 3:
            raise AppException(
                code="MENUS_MAX_DEPTH_EXCEEDED",
                message="Kedalaman menu maksimal 3 level",
                status_code=422,
            )
        menu.parent_id = parent_id

    if label is not None:
        menu.label = label
    if icon is not None:
        menu.icon = icon
    if path is not None:
        menu.path = path
    if order_index is not None:
        menu.order_index = order_index
    if is_active is not None:
        menu.is_active = is_active

    if role_ids is not None:
        # Replace menu_roles
        await db.execute(
            __import__("sqlalchemy", fromlist=["delete"]).delete(MenuRole).where(MenuRole.menu_id == menu_id)
        )
        for role_id in role_ids:
            db.add(MenuRole(menu_id=menu_id, role_id=role_id))

    await db.commit()
    await db.refresh(menu)
    await _invalidate_menu_cache()
    return menu


async def update_menu_order(db: AsyncSession, menu_id: uuid.UUID, order_index: int) -> Menu:
    menu = await _get_menu_or_404(db, menu_id)
    menu.order_index = order_index
    await db.commit()
    await db.refresh(menu)
    await _invalidate_menu_cache()
    return menu


async def assign_menu_roles(db: AsyncSession, menu_id: uuid.UUID, role_ids: list[uuid.UUID]) -> Menu:
    menu = await _get_menu_or_404(db, menu_id)
    from sqlalchemy import delete
    await db.execute(delete(MenuRole).where(MenuRole.menu_id == menu_id))
    for role_id in role_ids:
        db.add(MenuRole(menu_id=menu_id, role_id=role_id))
    await db.commit()
    await db.refresh(menu)
    await _invalidate_menu_cache()
    return menu


async def _delete_menu_recursive(db: AsyncSession, menu_id: uuid.UUID) -> None:
    """Delete menu and all children recursively."""
    children_result = await db.execute(select(Menu.id).where(Menu.parent_id == menu_id))
    child_ids = [row[0] for row in children_result.fetchall()]
    for child_id in child_ids:
        await _delete_menu_recursive(db, child_id)
    result = await db.execute(select(Menu).where(Menu.id == menu_id))
    menu = result.scalar_one_or_none()
    if menu:
        await db.delete(menu)


async def delete_menu(db: AsyncSession, menu_id: uuid.UUID) -> None:
    await _get_menu_or_404(db, menu_id)
    await _delete_menu_recursive(db, menu_id)
    await db.commit()
    await _invalidate_menu_cache()


async def get_my_menu(
    db: AsyncSession,
    user_id: str,
    user_roles: list[str],
    is_super_admin: bool,
) -> list[dict]:
    """Build the menu tree for a specific user, with Redis caching."""
    import json

    cache_key = f"menu_user:{user_id}"
    with contextlib.suppress(Exception):
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

    if is_super_admin:
        # Return all active menus
        result = await db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_roles))
            .where(Menu.is_active.is_(True))
            .order_by(Menu.order_index)
        )
        menus = list(result.scalars().all())
    else:
        # Get roles for this user (role IDs)
        role_result = await db.execute(
            select(Role.id).where(Role.slug.in_(user_roles))
        )
        role_ids = [row[0] for row in role_result.fetchall()]

        # Menus visible: menus with no role restriction OR menus with matching roles
        # Get menu IDs that have at least one matching role
        menu_with_role_result = await db.execute(
            select(MenuRole.menu_id).where(MenuRole.role_id.in_(role_ids))
        )
        menu_ids_with_role = {row[0] for row in menu_with_role_result.fetchall()}

        # Get all menus with role info
        all_menus_result = await db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_roles))
            .where(Menu.is_active.is_(True))
            .order_by(Menu.order_index)
        )
        all_menus = list(all_menus_result.scalars().all())

        # Filter: public (no roles) OR user has matching role
        menus = [
            m for m in all_menus
            if (not m.menu_roles) or (m.id in menu_ids_with_role)
        ]

    # Build tree
    tree = _build_tree(menus)

    # Cache
    with contextlib.suppress(Exception):
        await redis_client.setex(cache_key, 300, json.dumps(tree))

    return tree


def _build_tree(menus: list[Menu]) -> list[dict]:
    """Build a nested tree from flat menu list."""
    menu_map: dict[uuid.UUID, dict] = {}
    for m in menus:
        menu_map[m.id] = {
            "id": str(m.id),
            "label": m.label,
            "icon": m.icon,
            "path": m.path,
            "order_index": m.order_index,
            "children": [],
        }

    roots: list[dict] = []
    for m in menus:
        node = menu_map[m.id]
        if m.parent_id and m.parent_id in menu_map:
            menu_map[m.parent_id]["children"].append(node)
        else:
            roots.append(node)

    # Sort children
    def sort_children(nodes: list[dict]) -> list[dict]:
        nodes.sort(key=lambda x: x["order_index"])
        for n in nodes:
            n["children"] = sort_children(n["children"])
        return nodes

    return sort_children(roots)
