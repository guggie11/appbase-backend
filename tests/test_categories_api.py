"""Category endpoints, and the guarantee the whole feature rests on.

The claim is that the database refuses to delete a category another table
references. A test that only asks the service layer would prove nothing —
these go through the API, and one goes through a real foreign key.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.seed import seed_permissions, seed_roles
from app.models.rbac import Permission, RolePermission

PASSWORD = "Str0ng@Pass1"
PREFIX = "/api/v1/categories"


async def _actor(async_client, test_db, create_test_user, create_role,
                 assign_role, email, slugs):
    await seed_permissions(test_db)
    await seed_roles(test_db)
    role = await create_role(f"cat-{email.split('@')[0]}")
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


ALL = ["category.read", "category.create", "category.update", "category.delete"]


@pytest_asyncio.fixture
async def referencing_table(test_db):
    """A stand-in for a feature table that classifies its rows.

    Dropped unconditionally: leaving it behind holds a reference that blocks
    DROP TABLE categories at teardown and breaks unrelated tests.
    """
    await test_db.execute(text("DROP TABLE IF EXISTS fake_tickets"))
    await test_db.execute(
        text(
            """
            CREATE TABLE fake_tickets (
                id CHAR(36) PRIMARY KEY,
                status_id CHAR(36) NOT NULL
                    REFERENCES categories(id) ON DELETE RESTRICT
            )
            """
        )
    )
    await test_db.commit()
    try:
        yield
    finally:
        await test_db.rollback()
        await test_db.execute(text("DROP TABLE IF EXISTS fake_tickets"))
        await test_db.commit()


@pytest.mark.asyncio
async def test_other_features_fetch_by_group_code(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """The endpoint the rest of the application actually calls."""
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "cat-consumer@example.com", ALL)

    group_code = f"order-status-{uuid.uuid4().hex[:6]}"
    group = await async_client.post(
        f"{PREFIX}/groups",
        json={"name": "Order Status", "code": group_code},
        headers=headers,
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["data"]["id"]

    for code in ("draft", "shipped"):
        created = await async_client.post(
            PREFIX + "/",
            json={"group_id": group_id, "name": code.title(), "code": code},
            headers=headers,
        )
        assert created.status_code == 201, created.text

    res = await async_client.get(f"{PREFIX}/by-group/{group_code}", headers=headers)
    assert res.status_code == 200, res.text
    codes = {c["code"] for c in res.json()["data"]}
    assert codes == {"draft", "shipped"}


@pytest.mark.asyncio
async def test_deprecated_values_leave_the_picker(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "cat-deprecate@example.com", ALL)

    group = await async_client.post(
        f"{PREFIX}/groups", json={"name": "Doc Type", "code": "doc-type"},
        headers=headers,
    )
    group_id = group.json()["data"]["id"]

    item = await async_client.post(
        PREFIX + "/",
        json={"group_id": group_id, "name": "Memo", "code": "memo"},
        headers=headers,
    )
    item_id = item.json()["data"]["id"]

    dep = await async_client.post(
        f"{PREFIX}/{item_id}/deprecate",
        json={"reason": "replaced by 'note'"},
        headers=headers,
    )
    assert dep.status_code == 200, dep.text

    picker = await async_client.get(f"{PREFIX}/by-group/doc-type", headers=headers)
    assert picker.json()["data"] == []

    # Still visible where it is managed, otherwise it could never be restored.
    tree = await async_client.get(
        f"{PREFIX}/groups/{group_id}/tree", headers=headers
    )
    assert any(n["id"] == item_id for n in tree.json()["data"])


@pytest.mark.asyncio
async def test_deprecate_without_a_reason_is_refused(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "cat-noreason@example.com", ALL)

    group = await async_client.post(
        f"{PREFIX}/groups",
        json={"name": "Priority", "code": f"priority-{uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    item = await async_client.post(
        PREFIX + "/",
        json={"group_id": group.json()["data"]["id"], "name": "High", "code": "high"},
        headers=headers,
    )
    res = await async_client.post(
        f"{PREFIX}/{item.json()['data']['id']}/deprecate",
        json={"reason": ""},
        headers=headers,
    )
    assert res.status_code in (400, 422), res.status_code


@pytest.mark.asyncio
async def test_the_database_refuses_to_delete_a_referenced_category(
    test_db, referencing_table
):
    """The guarantee the design rests on.

    A feature table points at categories.id with ON DELETE RESTRICT. Deleting
    the row must fail at the database, not at an application check that a
    future table could forget to update.

    This runs in one session on purpose: the API client commits in a separate
    transaction, so a cross-session foreign key would be testing plumbing
    rather than the constraint.
    """
    from app.api.v1.categories import service
    from app.core.exceptions import AppException
    from app.schemas.category import CreateCategoryGroupRequest, CreateCategoryRequest

    group = await service.create_group(
        test_db, CreateCategoryGroupRequest(name="Ticket Status", code="ticket-status")
    )
    item = await service.create_category(
        test_db,
        CreateCategoryRequest(group_id=group.id, name="Open", code="open"),
    )

    # SQLAlchemy stores UUIDs on SQLite as 32 hex characters with no dashes;
    # a dashed string matches no row and the insert fails on the key itself.
    stored_id = (
        await test_db.execute(
            text("SELECT id FROM categories WHERE code = 'open'")
        )
    ).scalar_one()
    await test_db.execute(
        text("INSERT INTO fake_tickets (id, status_id) VALUES (:i, :s)").bindparams(
            i=uuid.uuid4().hex, s=stored_id
        )
    )
    await test_db.commit()

    try:
        with pytest.raises(AppException) as exc:
            await service.delete_category(test_db, item.id)
        # A clear answer, not a leaked 500.
        assert exc.value.status_code == 409
        assert "deprecate" in exc.value.message.lower()

        # Deprecating is the way out, and it leaves the reference intact.
        await service.deprecate_category(test_db, item.id, reason="no longer offered")
        still_there = (
            await test_db.execute(
                text("SELECT COUNT(*) FROM fake_tickets WHERE status_id = :s")
                .bindparams(s=stored_id)
            )
        ).scalar()
        assert still_there == 1
    finally:
        await test_db.rollback()
        await test_db.execute(text("DELETE FROM fake_tickets"))
        await test_db.commit()


@pytest.mark.asyncio
async def test_read_only_user_cannot_create(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "cat-viewer@example.com", ["category.read"])

    res = await async_client.post(
        f"{PREFIX}/groups", json={"name": "Nope", "code": "nope"}, headers=headers
    )
    assert res.status_code == 403, res.status_code


@pytest.mark.asyncio
async def test_editor_can_deprecate_but_not_delete(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """View and edit without delete — the reason actions are separate."""
    headers = await _actor(
        async_client, test_db, create_test_user, create_role, assign_role,
        "cat-editor@example.com",
        ["category.read", "category.create", "category.update"],
    )

    group = await async_client.post(
        f"{PREFIX}/groups", json={"name": "Stage", "code": "stage"}, headers=headers
    )
    item = await async_client.post(
        PREFIX + "/",
        json={"group_id": group.json()["data"]["id"], "name": "Early", "code": "early"},
        headers=headers,
    )
    item_id = item.json()["data"]["id"]

    allowed = await async_client.post(
        f"{PREFIX}/{item_id}/deprecate", json={"reason": "merged"}, headers=headers
    )
    assert allowed.status_code == 200, allowed.text

    refused = await async_client.delete(f"{PREFIX}/{item_id}", headers=headers)
    assert refused.status_code == 403, refused.status_code


@pytest.mark.asyncio
async def test_group_code_cannot_be_changed_through_the_api(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(async_client, test_db, create_test_user, create_role,
                           assign_role, "cat-immutable@example.com", ALL)

    group = await async_client.post(
        f"{PREFIX}/groups", json={"name": "Region", "code": "region"}, headers=headers
    )
    group_id = group.json()["data"]["id"]

    # Even if a client sends it, the schema has no such field.
    await async_client.patch(
        f"{PREFIX}/groups/{group_id}",
        json={"name": "Regions", "code": "regions"},
        headers=headers,
    )
    res = await async_client.get(f"{PREFIX}/groups/{group_id}", headers=headers)
    assert res.json()["data"]["code"] == "region"
