"""Platform roles must be immutable from the API, not just hidden in the UI.

Hiding the button is cosmetic: anyone can still call the endpoint. If Super
Admin's permissions can be stripped, the deployment locks itself out.
"""
import pytest
from sqlalchemy import select

from app.core.seed import seed_permissions, seed_role_permissions, seed_roles
from app.models.rbac import Role

PASSWORD = "Admin@12345"


async def _seed(db) -> Role:
    await seed_permissions(db)
    await seed_roles(db)
    await seed_role_permissions(db)
    return (await db.execute(select(Role).where(Role.slug == "super-admin"))).scalar_one()


async def _admin_headers(async_client, create_test_user, assign_role, email, role):
    """Log in for real: write endpoints also require a matching CSRF token,
    so a bare bearer header would be rejected before the role lock is reached.
    """
    user = await create_test_user(email=email, password=PASSWORD)
    await assign_role(user, role)

    res = await async_client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert res.status_code == 200, res.text
    token = res.json()["data"]["access_token"]
    csrf = res.cookies.get("csrf_token", "")
    return {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf}


@pytest.mark.asyncio
async def test_platform_role_cannot_be_updated(
    async_client, test_db, create_test_user, assign_role
):
    role = await _seed(test_db)
    headers = await _admin_headers(
        async_client, create_test_user, assign_role, "lock-update@example.com", role
    )

    res = await async_client.put(
        f"/api/v1/roles/{role.id}",
        json={"name": "Renamed", "description": "nope"},
        headers=headers,
    )

    assert res.status_code == 403, f"platform role was editable: {res.status_code} {res.text}"
    assert "PLATFORM_ROLE_LOCKED" in res.text, res.text


@pytest.mark.asyncio
async def test_platform_role_cannot_be_deleted(
    async_client, test_db, create_test_user, assign_role
):
    role = await _seed(test_db)
    headers = await _admin_headers(
        async_client, create_test_user, assign_role, "lock-delete@example.com", role
    )

    res = await async_client.delete(f"/api/v1/roles/{role.id}", headers=headers)

    assert res.status_code == 403, f"platform role was deletable: {res.status_code}"
    assert "PLATFORM_ROLE_LOCKED" in res.text, res.text


@pytest.mark.asyncio
async def test_platform_role_permissions_cannot_be_changed(
    async_client, test_db, create_test_user, assign_role
):
    """The dangerous one: stripping these would lock everyone out."""
    role = await _seed(test_db)
    headers = await _admin_headers(
        async_client, create_test_user, assign_role, "lock-perms@example.com", role
    )

    res = await async_client.put(
        f"/api/v1/roles/{role.id}/permissions",
        json={"permission_ids": []},
        headers=headers,
    )

    assert res.status_code == 403, f"platform permissions were editable: {res.status_code}"
    assert "PLATFORM_ROLE_LOCKED" in res.text, res.text


@pytest.mark.asyncio
async def test_custom_role_remains_editable(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """The lock must be narrow — ordinary roles stay fully manageable."""
    admin_role = await _seed(test_db)
    headers = await _admin_headers(
        async_client, create_test_user, assign_role, "lock-custom@example.com", admin_role
    )

    target = await create_role("editable-role")

    res = await async_client.put(
        f"/api/v1/roles/{target.id}",
        json={"name": "Renamed", "description": "fine"},
        headers=headers,
    )
    assert res.status_code == 200, f"custom role should stay editable: {res.text}"
