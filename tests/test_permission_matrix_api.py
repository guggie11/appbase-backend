"""The matrix endpoint, which the Roles & Permissions screen is built on."""
import pytest
from sqlalchemy import select

from app.core.seed import seed_permissions, seed_role_permissions, seed_roles
from app.models.rbac import Role

PASSWORD = "Admin@12345"


async def _headers(async_client, test_db, create_test_user, assign_role, email):
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
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


@pytest.mark.asyncio
async def test_matrix_endpoint_returns_actions_and_rows(
    async_client, test_db, create_test_user, assign_role
):
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "mx-shape@example.com"
    )

    res = await async_client.get("/api/v1/permissions/matrix", headers=headers)
    assert res.status_code == 200, res.text

    data = res.json()["data"]
    assert data["actions"] == ["read", "create", "update", "delete", "approve"]
    assert len(data["rows"]) > 0

    modules = {r["module"] for r in data["rows"]}
    for expected in ("users", "menu", "settings"):
        assert expected in modules


@pytest.mark.asyncio
async def test_matrix_cells_carry_what_the_ui_needs(
    async_client, test_db, create_test_user, assign_role
):
    """Without an id the UI cannot tell the backend what was ticked."""
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "mx-cells@example.com"
    )

    res = await async_client.get("/api/v1/permissions/matrix", headers=headers)
    rows = {r["module"]: r for r in res.json()["data"]["rows"]}

    read_cell = rows["users"]["cells"]["read"]
    assert read_cell["available"] is True
    assert read_cell["slug"] == "users.read"
    assert read_cell["id"], "available cell has no permission id"
    assert read_cell["description"], "available cell has no description"

    # Dashboard cannot be created or deleted; the cell must say so rather
    # than render as an empty, un-ticked box.
    blank = rows["dashboard"]["cells"]["create"]
    assert blank["available"] is False
    assert blank["slug"] is None
    assert blank["id"] is None


@pytest.mark.asyncio
async def test_matrix_flags_destructive_cells(
    async_client, test_db, create_test_user, assign_role
):
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "mx-danger@example.com"
    )

    res = await async_client.get("/api/v1/permissions/matrix", headers=headers)
    rows = {r["module"]: r for r in res.json()["data"]["rows"]}

    assert rows["users"]["cells"]["delete"]["is_dangerous"] is True
    assert rows["users"]["cells"]["read"]["is_dangerous"] is False


@pytest.mark.asyncio
async def test_matrix_keeps_slugs_without_a_column(
    async_client, test_db, create_test_user, assign_role
):
    """menu.manage and permissions.assign have no column of their own.

    Dropping them from the response would hide rights a role actually holds.
    """
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "mx-extra@example.com"
    )

    res = await async_client.get("/api/v1/permissions/matrix", headers=headers)
    rows = {r["module"]: r for r in res.json()["data"]["rows"]}

    assert "menu.manage" in rows["menu"]["extra"]
    assert "permissions.assign" in rows["permissions"]["extra"]


@pytest.mark.asyncio
async def test_matrix_requires_permission(async_client, test_db, create_test_user):
    """An anonymous caller must not be able to enumerate the catalogue."""
    res = await async_client.get("/api/v1/permissions/matrix")
    assert res.status_code in (401, 403), res.status_code
