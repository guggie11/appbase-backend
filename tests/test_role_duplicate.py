"""Duplicating a role, and reporting how many users hold it."""
import uuid

import pytest
from sqlalchemy import select

from app.core.seed import seed_permissions, seed_role_permissions, seed_roles
from app.models.rbac import Role, RolePermission

PASSWORD = "Admin@12345"


async def _admin_headers(async_client, test_db, create_test_user, assign_role, email):
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_role_permissions(test_db)
    role = (
        await test_db.execute(select(Role).where(Role.slug == "super-admin"))
    ).scalar_one()

    user = await create_test_user(email=email, password=PASSWORD)
    await assign_role(user, role)

    res = await async_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert res.status_code == 200, res.text
    return {
        "Authorization": f"Bearer {res.json()['data']['access_token']}",
        "X-CSRF-Token": res.cookies.get("csrf_token", ""),
    }, role


@pytest.mark.asyncio
async def test_duplicate_copies_every_permission(
    async_client, test_db, create_test_user, assign_role
):
    """The point of duplicating is not re-ticking twenty boxes by hand."""
    headers, source = await _admin_headers(
        async_client, test_db, create_test_user, assign_role, "dup-all@example.com"
    )

    res = await async_client.post(
        f"/api/v1/roles/{source.id}/duplicate",
        json={"name": "Copy Of Super Admin"},
        headers=headers,
    )
    assert res.status_code == 200, res.text

    copy_id = res.json()["data"]["id"]
    source_perms = (
        await test_db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == source.id)
        )
    ).scalars().all()
    copy_perms = (
        await test_db.execute(
            select(RolePermission.permission_id).where(
                RolePermission.role_id == uuid.UUID(copy_id)
            )
        )
    ).scalars().all()

    assert set(copy_perms) == set(source_perms)
    assert len(copy_perms) > 0, "copied a role that grants nothing"


@pytest.mark.asyncio
async def test_duplicate_of_platform_role_is_not_itself_platform(
    async_client, test_db, create_test_user, assign_role
):
    """Otherwise the copy would inherit the lock and be uneditable too."""
    headers, source = await _admin_headers(
        async_client, test_db, create_test_user, assign_role, "dup-kind@example.com"
    )

    res = await async_client.post(
        f"/api/v1/roles/{source.id}/duplicate",
        json={"name": "Admin Variant"},
        headers=headers,
    )
    assert res.status_code == 200, res.text

    body = res.json()["data"]
    assert body["kind"] == "custom", f"copy inherited kind={body['kind']}"
    assert body["is_system"] is False


@pytest.mark.asyncio
async def test_duplicate_rejects_an_existing_name(
    async_client, test_db, create_test_user, assign_role
):
    headers, source = await _admin_headers(
        async_client, test_db, create_test_user, assign_role, "dup-clash@example.com"
    )

    res = await async_client.post(
        f"/api/v1/roles/{source.id}/duplicate",
        json={"name": "Super Admin"},
        headers=headers,
    )
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_role_list_reports_real_user_counts(
    async_client, test_db, create_test_user, assign_role
):
    """The schema defaults user_count to 0, which would be a plausible lie."""
    headers, admin_role = await _admin_headers(
        async_client, test_db, create_test_user, assign_role, "count-admin@example.com"
    )

    res = await async_client.get("/api/v1/roles/?per_page=50", headers=headers)
    assert res.status_code == 200, res.text
    before = {r["slug"]: r["user_count"] for r in res.json()["data"]}

    extra = await create_test_user(email="count-second@example.com", password=PASSWORD)
    await assign_role(extra, admin_role)

    res = await async_client.get("/api/v1/roles/?per_page=50", headers=headers)
    after = {r["slug"]: r["user_count"] for r in res.json()["data"]}

    # Measure the delta: the test DB is shared across this module, so an
    # absolute count would just encode whatever ran first.
    assert after["super-admin"] == before["super-admin"] + 1, (before, after)
    assert after["super-admin"] > 0, "schema default would report 0 for every role"
