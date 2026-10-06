"""CSV import must report per-row outcomes, not stop at the first bad line."""
import io

import pytest
from sqlalchemy import select

from app.core.seed import seed_permissions, seed_role_permissions, seed_roles
from app.models.rbac import Role
from app.models.user import User

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
    return {
        "Authorization": f"Bearer {res.json()['data']['access_token']}",
        "X-CSRF-Token": res.cookies.get("csrf_token", ""),
    }


def _csv(text: str):
    return {"file": ("users.csv", io.BytesIO(text.encode()), "text/csv")}


@pytest.mark.asyncio
async def test_import_creates_users(
    async_client, test_db, create_test_user, assign_role
):
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "imp-ok@example.com"
    )

    res = await async_client.post(
        "/api/v1/users/import",
        files=_csv("name,email\nAda Lovelace,ada@example.com\nAlan Turing,alan@example.com\n"),
        headers=headers,
    )
    assert res.status_code == 200, res.text

    data = res.json()["data"]
    assert data["created"] == 2, data
    assert data["failed"] == 0, data

    row = (
        await test_db.execute(select(User).where(User.email == "ada@example.com"))
    ).scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
async def test_bad_rows_do_not_abort_the_good_ones(
    async_client, test_db, create_test_user, assign_role
):
    """One malformed line in fifty must not discard the other forty-nine."""
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "imp-mixed@example.com"
    )

    res = await async_client.post(
        "/api/v1/users/import",
        files=_csv(
            "name,email\n"
            "Good One,good1@example.com\n"
            "Missing Email,\n"
            "Bad Email,not-an-email\n"
            "Good Two,good2@example.com\n"
        ),
        headers=headers,
    )
    assert res.status_code == 200, res.text

    data = res.json()["data"]
    assert data["created"] == 2, data
    assert data["failed"] == 2, data
    # The report must say which line and why, or it is unusable.
    assert len(data["errors"]) == 2, data
    assert all("row" in e and "reason" in e for e in data["errors"]), data


@pytest.mark.asyncio
async def test_duplicate_email_is_reported_not_crashed(
    async_client, test_db, create_test_user, assign_role
):
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "imp-dup@example.com"
    )
    await create_test_user(email="taken@example.com")

    res = await async_client.post(
        "/api/v1/users/import",
        files=_csv("name,email\nSomeone,taken@example.com\nFresh,fresh@example.com\n"),
        headers=headers,
    )
    assert res.status_code == 200, res.text

    data = res.json()["data"]
    assert data["created"] == 1, data
    assert data["failed"] == 1, data


@pytest.mark.asyncio
async def test_missing_email_column_is_rejected_clearly(
    async_client, test_db, create_test_user, assign_role
):
    headers = await _headers(
        async_client, test_db, create_test_user, assign_role, "imp-cols@example.com"
    )

    res = await async_client.post(
        "/api/v1/users/import",
        files=_csv("name,nickname\nNobody,nope\n"),
        headers=headers,
    )
    assert res.status_code == 400, res.text
    assert "email" in res.text.lower()
