"""Menus gated by permission rather than by role.

Binding a menu to a role means every new role has to be remembered and added
to every relevant menu. Binding it to a permission means the menu appears for
whoever holds that right — including roles created tomorrow.
"""
import uuid

import pytest
from sqlalchemy import select

from app.api.v1.menus import service
from app.core.seed import seed_permissions, seed_role_permissions, seed_roles
from app.models.menu import Menu
from app.models.rbac import Permission, Role, RolePermission


async def _menu(db, label, *, path=None, permission=None, parent_id=None, order=0) -> Menu:
    row = Menu(
        id=uuid.uuid4(),
        label=label,
        path=path or f"/{label.lower()}",
        parent_id=parent_id,
        order_index=order,
        is_active=True,
        required_permission=permission,
    )
    db.add(row)
    await db.flush()
    return row


async def _role_with(db, slug: str, permission_slugs: list[str]) -> Role:
    await seed_permissions(db)
    role = Role(id=uuid.uuid4(), name=slug, slug=slug, is_system=False, is_active=True)
    db.add(role)
    await db.flush()
    for s in permission_slugs:
        perm = (
            await db.execute(select(Permission).where(Permission.slug == s))
        ).scalar_one()
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    await db.commit()
    return role


def _labels(tree: list[dict]) -> set[str]:
    out = set()
    for node in tree:
        out.add(node["label"])
        out |= _labels(node.get("children") or [])
    return out


@pytest.mark.asyncio
async def test_menu_hidden_without_the_required_permission(test_db):
    await _menu(test_db, "Audit", permission="audit.read")
    await test_db.commit()

    tree = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=[], is_super_admin=False,
        permissions=[],
    )
    assert "Audit" not in _labels(tree)


@pytest.mark.asyncio
async def test_menu_shown_when_the_permission_is_held(test_db):
    await _menu(test_db, "Audit", permission="audit.read")
    await test_db.commit()

    tree = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=[], is_super_admin=False,
        permissions=["audit.read"],
    )
    assert "Audit" in _labels(tree)


@pytest.mark.asyncio
async def test_unrestricted_menu_stays_public(test_db):
    """A menu with no requirement must not become invisible."""
    await _menu(test_db, "Dashboard", permission=None)
    await test_db.commit()

    tree = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=[], is_super_admin=False,
        permissions=[],
    )
    assert "Dashboard" in _labels(tree)


@pytest.mark.asyncio
async def test_parent_survives_when_a_child_is_visible(test_db):
    """Otherwise the visible child is orphaned and vanishes from the tree.

    The parent "Administration" itself requires nothing, but a naive filter
    that drops parents whose own permission fails would take its children
    down with it.
    """
    parent = await _menu(test_db, "Administration", permission="settings.manage")
    await _menu(test_db, "Users", permission="users.read", parent_id=parent.id)
    await test_db.commit()

    tree = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=[], is_super_admin=False,
        permissions=["users.read"],  # not settings.manage
    )

    labels = _labels(tree)
    assert "Users" in labels, "visible child disappeared"
    assert "Administration" in labels, "parent dropped, orphaning its child"


@pytest.mark.asyncio
async def test_parent_hidden_when_no_child_is_visible(test_db):
    """The rescue must be narrow: an empty branch is clutter."""
    parent = await _menu(test_db, "Administration", permission="settings.manage")
    await _menu(test_db, "Users", permission="users.read", parent_id=parent.id)
    await test_db.commit()

    tree = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=[], is_super_admin=False,
        permissions=["dashboard.read"],
    )
    assert "Administration" not in _labels(tree)


@pytest.mark.asyncio
async def test_super_admin_sees_everything(test_db):
    await _menu(test_db, "Audit", permission="audit.read")
    await test_db.commit()

    tree = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=["super-admin"],
        is_super_admin=True, permissions=[],
    )
    assert "Audit" in _labels(tree)


@pytest.mark.asyncio
async def test_legacy_role_binding_still_works(test_db):
    """Existing deployments bind menus to roles; that must not break."""
    from app.models.menu import MenuRole

    role = await _role_with(test_db, "legacy-viewer", [])
    menu = await _menu(test_db, "LegacyOnly", permission=None)
    test_db.add(MenuRole(menu_id=menu.id, role_id=role.id))
    await test_db.commit()

    visible = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=["legacy-viewer"],
        is_super_admin=False, permissions=[],
    )
    assert "LegacyOnly" in _labels(visible)

    hidden = await service.get_my_menu(
        test_db, user_id=str(uuid.uuid4()), user_roles=["someone-else"],
        is_super_admin=False, permissions=[],
    )
    assert "LegacyOnly" not in _labels(hidden)


@pytest.mark.asyncio
async def test_cache_does_not_leak_between_permission_sets(test_db):
    """Same user id, different rights — the cache key must notice."""
    await _menu(test_db, "Audit", permission="audit.read")
    await test_db.commit()
    uid = str(uuid.uuid4())

    with_perm = await service.get_my_menu(
        test_db, user_id=uid, user_roles=[], is_super_admin=False,
        permissions=["audit.read"],
    )
    without = await service.get_my_menu(
        test_db, user_id=uid, user_roles=[], is_super_admin=False,
        permissions=[],
    )

    assert "Audit" in _labels(with_perm)
    assert "Audit" not in _labels(without), "cache served another permission set"


@pytest.mark.asyncio
async def test_required_permission_round_trips_through_the_api(
    async_client, test_db, create_test_user, assign_role
):
    """Storing it is half the job — it has to survive create and update."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_role_permissions(test_db)
    role = (
        await test_db.execute(select(Role).where(Role.slug == "super-admin"))
    ).scalar_one()

    admin = await create_test_user(email="menu-perm@example.com", password="Admin@12345")
    await assign_role(admin, role)
    login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "menu-perm@example.com", "password": "Admin@12345"},
    )
    headers = {
        "Authorization": f"Bearer {login.json()['data']['access_token']}",
        "X-CSRF-Token": login.cookies.get("csrf_token", ""),
    }

    created = await async_client.post(
        "/api/v1/menus/",
        json={"label": "Audit", "path": "/audit", "required_permission": "audit.read"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    assert body["required_permission"] == "audit.read", body

    updated = await async_client.put(
        f"/api/v1/menus/{body['id']}",
        json={"required_permission": "settings.read"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["required_permission"] == "settings.read"
