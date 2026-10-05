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
        .options(selectinload(Menu.menu_roles).selectinload(MenuRole.role))
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
    required_permission: str | None = None,
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
        required_permission=required_permission,
    )
    db.add(menu)
    await db.flush()

    # Assign roles
    if role_ids:
        for role_id in role_ids:
            menu_role = MenuRole(menu_id=menu.id, role_id=role_id)
            db.add(menu_role)

    await db.commit()
    await _invalidate_menu_cache()
    # Re-query eagerly: db.refresh() does not reload selectinload relations,
    # so serialising the stale instance triggers lazy IO (MissingGreenlet).
    return await _get_menu_or_404(db, menu.id)


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
    # Sentinel: None means "leave alone", while an explicit empty string
    # clears the requirement and makes the menu public again.
    required_permission: str | None = None,
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
    if required_permission is not None:
        menu.required_permission = required_permission or None

    if role_ids is not None:
        # Replace menu_roles
        await db.execute(
            __import__("sqlalchemy", fromlist=["delete"]).delete(MenuRole).where(MenuRole.menu_id == menu_id)
        )
        for role_id in role_ids:
            db.add(MenuRole(menu_id=menu_id, role_id=role_id))

    await db.commit()
    await _invalidate_menu_cache()
    return await _get_menu_or_404(db, menu_id)


async def update_menu_order(db: AsyncSession, menu_id: uuid.UUID, order_index: int) -> Menu:
    menu = await _get_menu_or_404(db, menu_id)
    menu.order_index = order_index
    await db.commit()
    await _invalidate_menu_cache()
    # Re-query: db.refresh() does not reload selectinload relations, so serialising
    # the stale instance triggers lazy IO (MissingGreenlet) outside the greenlet.
    return await _get_menu_or_404(db, menu_id)


async def reorder_siblings(
    db: AsyncSession,
    parent_id: uuid.UUID | None,
    menu_ids: list[uuid.UUID],
) -> list[Menu]:
    """Atomically renumber one sibling group to order_index 0..n-1.

    ``menu_ids`` must be the COMPLETE ordered sibling set for ``parent_id``.
    Validation happens before any write, so a rejected payload leaves the
    stored ordering untouched.
    """
    if not menu_ids:
        raise AppException(
            code="MENUS_REORDER_EMPTY",
            message="Daftar menu tidak boleh kosong",
            status_code=422,
        )

    if len(set(menu_ids)) != len(menu_ids):
        raise AppException(
            code="MENUS_REORDER_DUPLICATE",
            message="Daftar menu mengandung ID duplikat",
            status_code=422,
        )

    if parent_id is not None:
        parent_exists = await db.execute(select(Menu.id).where(Menu.id == parent_id))
        if parent_exists.scalar_one_or_none() is None:
            raise AppException(
                code="MENUS_NOT_FOUND",
                message="Parent menu tidak ditemukan",
                status_code=404,
            )

    # Lock the whole sibling group so concurrent reorders serialise.
    sibling_query = select(Menu).where(
        Menu.parent_id.is_(None) if parent_id is None else Menu.parent_id == parent_id
    )
    with contextlib.suppress(NotImplementedError):
        sibling_query = sibling_query.with_for_update()
    sibling_result = await db.execute(sibling_query)
    siblings = {m.id: m for m in sibling_result.scalars().all()}

    unknown = [mid for mid in menu_ids if mid not in siblings]
    if unknown:
        raise AppException(
            code="MENUS_REORDER_INVALID_MEMBER",
            message="Menu tidak ditemukan pada grup parent yang dimaksud",
            status_code=422,
        )

    missing = [mid for mid in siblings if mid not in menu_ids]
    if missing:
        raise AppException(
            code="MENUS_REORDER_INCOMPLETE",
            message="Daftar menu harus memuat seluruh sibling pada grup ini",
            status_code=422,
        )

    for position, menu_id in enumerate(menu_ids):
        siblings[menu_id].order_index = position

    await db.commit()
    await _invalidate_menu_cache()
    return await list_menus(db)


async def assign_menu_roles(db: AsyncSession, menu_id: uuid.UUID, role_ids: list[uuid.UUID]) -> Menu:
    await _get_menu_or_404(db, menu_id)
    from sqlalchemy import delete
    await db.execute(delete(MenuRole).where(MenuRole.menu_id == menu_id))
    for role_id in role_ids:
        db.add(MenuRole(menu_id=menu_id, role_id=role_id))
    await db.commit()
    await _invalidate_menu_cache()
    return await _get_menu_or_404(db, menu_id)


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


def _visible_menus(
    all_menus: list[Menu],
    permissions: set[str],
    menu_ids_with_role: set,
) -> list[Menu]:
    """Keep the items this user may see, plus the parents that hold them.

    An item qualifies when it demands nothing, when the user holds its
    required permission, or when it is bound to one of the user's roles
    (the pre-v1.2c mechanism, kept so existing deployments keep working).

    Parents are then pulled back in: dropping a parent whose own permission
    fails would orphan its visible children and erase them from the tree.
    """
    by_id = {m.id: m for m in all_menus}

    def qualifies(m: Menu) -> bool:
        if m.required_permission:
            return m.required_permission in permissions
        if m.menu_roles:
            return m.id in menu_ids_with_role
        return True

    keep = {m.id for m in all_menus if qualifies(m)}

    # Walk up from every kept item so no visible child is left without a
    # branch to hang on. An empty branch is never rescued.
    for menu_id in list(keep):
        parent_id = by_id[menu_id].parent_id
        while parent_id is not None and parent_id not in keep:
            keep.add(parent_id)
            parent = by_id.get(parent_id)
            if parent is None:
                break
            parent_id = parent.parent_id

    return [m for m in all_menus if m.id in keep]


async def get_my_menu(
    db: AsyncSession,
    user_id: str,
    user_roles: list[str],
    is_super_admin: bool,
    permissions: list[str] | None = None,
) -> list[dict]:
    """Build the menu tree for a specific user, with Redis caching."""
    import hashlib
    import json

    held = set(permissions or [])

    # The key must cover the rights, not just the identity: the same user can
    # be previewed as another role, and stale entries would leak one set of
    # menus into another.
    fingerprint = hashlib.sha1(
        "|".join(sorted(held) + ["::"] + sorted(user_roles) + [str(is_super_admin)]).encode()
    ).hexdigest()[:16]
    cache_key = f"menu_user:{user_id}:{fingerprint}"

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
        role_result = await db.execute(
            select(Role.id).where(Role.slug.in_(user_roles))
        )
        role_ids = [row[0] for row in role_result.fetchall()]

        menu_with_role_result = await db.execute(
            select(MenuRole.menu_id).where(MenuRole.role_id.in_(role_ids))
        )
        menu_ids_with_role = {row[0] for row in menu_with_role_result.fetchall()}

        all_menus_result = await db.execute(
            select(Menu)
            .options(selectinload(Menu.menu_roles))
            .where(Menu.is_active.is_(True))
            .order_by(Menu.order_index)
        )
        all_menus = list(all_menus_result.scalars().all())

        menus = _visible_menus(all_menus, held, menu_ids_with_role)

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
