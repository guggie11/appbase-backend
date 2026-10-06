"""Granting a single action must actually work at the endpoint.

Splitting menu.manage into create/update/delete is pointless if every write
endpoint still demands the old catch-all: the new permissions would be
decorative. Equally, anyone still holding the catch-all must keep working.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.seed import seed_permissions
from app.models.menu import Menu
from app.models.rbac import Permission, RolePermission

PASSWORD = "Probe@12345"


async def _actor(async_client, test_db, create_test_user, create_role, assign_role,
                 email, slugs):
    """A user holding exactly the given permission slugs."""
    await seed_permissions(test_db)
    role = await create_role(f"probe-{email.split('@')[0]}")
    for slug in slugs:
        perm = (
            await test_db.execute(select(Permission).where(Permission.slug == slug))
        ).scalar_one()
        test_db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    await test_db.commit()

    user = await create_test_user(email=email, password=PASSWORD)
    await assign_role(user, role)

    res = await async_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {
        "Authorization": f"Bearer {res.json()['data']['access_token']}",
        "X-CSRF-Token": res.cookies.get("csrf_token", ""),
    }


async def _a_menu(test_db) -> Menu:
    row = Menu(id=uuid.uuid4(), label="Probe", path="/probe", order_index=99,
               is_active=True)
    test_db.add(row)
    await test_db.commit()
    return row


@pytest.mark.asyncio
async def test_menu_create_permission_allows_creating(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "menu-creator@example.com",
                           ["menu.read", "menu.create"])

    res = await async_client.post(
        "/api/v1/menus/",
        json={"label": "Made by creator", "path": "/made-by-creator"},
        headers=headers,
    )
    assert res.status_code == 201, f"menu.create did not grant creation: {res.text}"


@pytest.mark.asyncio
async def test_view_and_edit_role_cannot_delete(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """The exact capability the split exists to provide."""
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "menu-editor@example.com",
                           ["menu.read", "menu.update"])
    target = await _a_menu(test_db)

    edit = await async_client.put(
        f"/api/v1/menus/{target.id}", json={"label": "Renamed"}, headers=headers
    )
    assert edit.status_code == 200, f"menu.update did not grant editing: {edit.text}"

    delete = await async_client.delete(
        f"/api/v1/menus/{target.id}", headers=headers
    )
    assert delete.status_code == 403, f"editor was able to delete: {delete.status_code}"


@pytest.mark.asyncio
async def test_legacy_manage_still_grants_everything(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """An upgrade must not silently revoke access from existing holders."""
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "menu-legacy@example.com",
                           ["menu.read", "menu.manage"])
    target = await _a_menu(test_db)

    edit = await async_client.put(
        f"/api/v1/menus/{target.id}", json={"label": "Legacy rename"}, headers=headers
    )
    assert edit.status_code == 200, f"legacy manage lost edit: {edit.text}"

    delete = await async_client.delete(
        f"/api/v1/menus/{target.id}", headers=headers
    )
    assert delete.status_code == 200, f"legacy manage lost delete: {delete.text}"


@pytest.mark.asyncio
async def test_manage_does_not_grant_reading(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """`.manage` meant "may change things", never "may see things".

    Letting it satisfy a read guard would hand write-only grants a view of
    data they were never given.
    """
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "menu-writeonly@example.com",
                           ["menu.manage"])

    res = await async_client.get("/api/v1/menus/", headers=headers)
    assert res.status_code == 403, (
        f"menu.manage alone unlocked reading: {res.status_code}"
    )


@pytest.mark.asyncio
async def test_read_only_role_is_still_refused(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """The guard must narrow, not disappear."""
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "menu-viewer@example.com", ["menu.read"])

    res = await async_client.post(
        "/api/v1/menus/", json={"label": "Nope", "path": "/nope"}, headers=headers
    )
    assert res.status_code == 403, f"read-only user created a menu: {res.status_code}"
