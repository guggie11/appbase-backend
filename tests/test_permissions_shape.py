"""GET /permissions must wrap its payload like every other endpoint.

It was the only route returning a bare array. The frontend reads
`res.data.data` everywhere, so the permission catalogue silently arrived as
undefined and the matrix rendered "0 / 0" with no error anywhere.
"""
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
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


@pytest.mark.asyncio
async def test_permissions_response_is_wrapped(
    async_client, test_db, create_test_user, assign_role
):
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "perm-shape@example.com"
    )

    res = await async_client.get("/api/v1/permissions/", headers=headers)
    assert res.status_code == 200, res.text

    body = res.json()
    assert isinstance(body, dict), f"expected a wrapped object, got {type(body)}"
    assert "data" in body, f"missing data envelope: {list(body)}"
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0, "catalogue came back empty"


@pytest.mark.asyncio
async def test_permissions_carry_their_metadata(
    async_client, test_db, create_test_user, assign_role
):
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "perm-meta@example.com"
    )

    res = await async_client.get("/api/v1/permissions/", headers=headers)
    rows = {p["slug"]: p for p in res.json()["data"]}

    assert rows["users.read"]["description"], "description missing from the API"
    assert rows["users.read"]["group"] == "Users"
    assert rows["users.delete"]["is_dangerous"] is True
    assert rows["users.read"]["is_dangerous"] is False
