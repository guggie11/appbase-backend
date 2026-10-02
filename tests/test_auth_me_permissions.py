"""GET /auth/me must carry the caller's roles and permissions.

Without them the frontend cannot evaluate permissions and falls back to
"every active user can do everything" — which is how the Admin Console shipped
with permission checks that never actually denied anything.
"""
import pytest


@pytest.mark.asyncio
async def test_me_exposes_roles_and_permissions(
    async_client, create_test_user, create_role, assign_role, auth_headers
):
    user = await create_test_user(email="perm@example.com")
    role = await create_role("me-editor", permissions=["users.read", "menu.read"])
    await assign_role(user, role)

    res = await async_client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert res.status_code == 200, res.text
    data = res.json()["data"]

    assert "roles" in data, "/auth/me must expose roles"
    assert "permissions" in data, "/auth/me must expose permissions"
    assert sorted(data["permissions"]) == ["menu.read", "users.read"]
    assert [r["slug"] for r in data["roles"]] == ["me-editor"]


@pytest.mark.asyncio
async def test_permissions_are_flat_slugs(
    async_client, create_test_user, create_role, assign_role, auth_headers
):
    """A flat slug list keeps the UI lookup trivial."""
    user = await create_test_user(email="flat@example.com")
    role = await create_role("me-viewer", permissions=["users.read"])
    await assign_role(user, role)

    res = await async_client.get("/api/v1/auth/me", headers=auth_headers(user))
    perms = res.json()["data"]["permissions"]

    assert perms == ["users.read"]
    assert all(isinstance(p, str) for p in perms)


@pytest.mark.asyncio
async def test_permissions_are_deduplicated(
    async_client, create_test_user, create_role, assign_role, auth_headers
):
    """Two roles granting the same permission must not list it twice."""
    user = await create_test_user(email="dupe@example.com")
    a = await create_role("me-role-a", permissions=["users.read", "menu.read"])
    b = await create_role("me-role-b", permissions=["users.read", "roles.read"])
    await assign_role(user, a)
    await assign_role(user, b)

    res = await async_client.get("/api/v1/auth/me", headers=auth_headers(user))
    perms = res.json()["data"]["permissions"]

    assert len(perms) == len(set(perms)), f"duplicates: {perms}"
    assert sorted(perms) == ["menu.read", "roles.read", "users.read"]


@pytest.mark.asyncio
async def test_active_user_without_roles_gets_nothing(
    async_client, create_test_user, auth_headers
):
    """The exact case the old stub got wrong.

    `status == "active"` was treated as "has every permission", so a user with
    no role at all saw the whole admin surface.
    """
    user = await create_test_user(email="bare@example.com", status="active")

    res = await async_client.get("/api/v1/auth/me", headers=auth_headers(user))
    data = res.json()["data"]

    assert data["permissions"] == [], f"roleless active user got {data['permissions']}"
    assert data["roles"] == []
