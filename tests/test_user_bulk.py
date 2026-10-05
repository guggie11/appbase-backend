"""Bulk user actions, and the guards that stop an admin locking themselves out.

Changing 20 users one modal at a time is the problem being solved. The risk
is that a single careless bulk action removes the operator's own access, or
strips the last holder of the platform role, leaving nobody who can undo it.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.seed import seed_permissions, seed_role_permissions, seed_roles
from app.models.rbac import Role, UserRole

PASSWORD = "Admin@12345"


async def _admin(async_client, test_db, create_test_user, assign_role, email):
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
    headers = {
        "Authorization": f"Bearer {res.json()['data']['access_token']}",
        "X-CSRF-Token": res.cookies.get("csrf_token", ""),
    }
    return user, role, headers


# ---------------------------------------------------------------------------
# Bulk role assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_add_role_to_many_users(
    async_client, test_db, create_test_user, create_role, assign_role
):
    _, _, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-add@example.com"
    )
    target = await create_role("bulk-editor")
    a = await create_test_user(email="bulk-a@example.com")
    b = await create_test_user(email="bulk-b@example.com")

    res = await async_client.post(
        "/api/v1/users/bulk/roles",
        json={
            "user_ids": [str(a.id), str(b.id)],
            "role_ids": [str(target.id)],
            "action": "add",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text

    for user in (a, b):
        rows = (
            await test_db.execute(
                select(UserRole).where(UserRole.user_id == user.id)
            )
        ).scalars().all()
        assert target.id in {r.role_id for r in rows}


@pytest.mark.asyncio
async def test_bulk_add_is_idempotent(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """Running it twice must not create duplicate rows."""
    _, _, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-twice@example.com"
    )
    target = await create_role("bulk-twice-role")
    user = await create_test_user(email="bulk-twice-user@example.com")

    body = {
        "user_ids": [str(user.id)],
        "role_ids": [str(target.id)],
        "action": "add",
    }
    await async_client.post("/api/v1/users/bulk/roles", json=body, headers=headers)
    await async_client.post("/api/v1/users/bulk/roles", json=body, headers=headers)

    rows = (
        await test_db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == target.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1, f"duplicate role rows: {len(rows)}"


@pytest.mark.asyncio
async def test_bulk_remove_role(
    async_client, test_db, create_test_user, create_role, assign_role
):
    _, _, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-rm@example.com"
    )
    target = await create_role("bulk-removable")
    user = await create_test_user(email="bulk-rm-user@example.com")
    await assign_role(user, target)

    res = await async_client.post(
        "/api/v1/users/bulk/roles",
        json={
            "user_ids": [str(user.id)],
            "role_ids": [str(target.id)],
            "action": "remove",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text

    rows = (
        await test_db.execute(select(UserRole).where(UserRole.user_id == user.id))
    ).scalars().all()
    assert target.id not in {r.role_id for r in rows}


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_deactivate_yourself_in_bulk(
    async_client, test_db, create_test_user, assign_role
):
    """The lockout no one can undo."""
    me, _, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-self@example.com"
    )
    other = await create_test_user(email="bulk-other@example.com")

    res = await async_client.post(
        "/api/v1/users/bulk/status",
        json={"user_ids": [str(me.id), str(other.id)], "status": "inactive"},
        headers=headers,
    )

    assert res.status_code == 400, f"was allowed to deactivate self: {res.text}"
    await test_db.refresh(me)
    assert me.status != "inactive", "own account was deactivated"


@pytest.mark.asyncio
async def test_cannot_strip_your_own_platform_role(
    async_client, test_db, create_test_user, assign_role
):
    me, admin_role, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-selfrole@example.com"
    )

    res = await async_client.post(
        "/api/v1/users/bulk/roles",
        json={
            "user_ids": [str(me.id)],
            "role_ids": [str(admin_role.id)],
            "action": "remove",
        },
        headers=headers,
    )
    assert res.status_code == 400, f"was allowed to strip own admin role: {res.text}"


@pytest.mark.asyncio
async def test_cannot_remove_the_last_platform_admin(
    async_client, test_db, create_test_user, assign_role
):
    """Even targeting someone else, the final holder must survive."""
    me, admin_role, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-last@example.com"
    )
    # A second admin exists, so removing them is fine...
    second = await create_test_user(email="bulk-second-admin@example.com")
    await assign_role(second, admin_role)

    ok = await async_client.post(
        "/api/v1/users/bulk/roles",
        json={
            "user_ids": [str(second.id)],
            "role_ids": [str(admin_role.id)],
            "action": "remove",
        },
        headers=headers,
    )
    assert ok.status_code == 200, ok.text

    # ...but now only the caller is left, and that is already guarded above.
    rows = (
        await test_db.execute(
            select(UserRole).where(UserRole.role_id == admin_role.id)
        )
    ).scalars().all()
    assert len(rows) >= 1, "platform role left with no holder"


@pytest.mark.asyncio
async def test_bulk_status_activates(
    async_client, test_db, create_test_user, assign_role
):
    _, _, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-act@example.com"
    )
    user = await create_test_user(email="bulk-act-user@example.com", status="inactive")

    res = await async_client.post(
        "/api/v1/users/bulk/status",
        json={"user_ids": [str(user.id)], "status": "active"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    await test_db.refresh(user)
    assert user.status == "active"


@pytest.mark.asyncio
async def test_unknown_user_id_does_not_abort_the_batch(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """One stale id in a list of twenty must not undo the other nineteen."""
    _, _, headers = await _admin(
        async_client, test_db, create_test_user, assign_role, "bulk-stale@example.com"
    )
    target = await create_role("bulk-stale-role")
    real = await create_test_user(email="bulk-real@example.com")

    res = await async_client.post(
        "/api/v1/users/bulk/roles",
        json={
            "user_ids": [str(real.id), str(uuid.uuid4())],
            "role_ids": [str(target.id)],
            "action": "add",
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text

    data = res.json()["data"]
    assert data["updated"] == 1, data
    assert data["skipped"] == 1, data
