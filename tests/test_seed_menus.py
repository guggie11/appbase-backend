"""Seeding the default menu.

A fresh install used to end up with a single menu row, so an admin could log
in and then had nowhere to go. These tests pin the two things that made that
possible: a seed that never created menus, and a migration that gave up
silently when it found no parent to attach to.
"""
import pytest
from sqlalchemy import select

from app.core.seed import seed_menus, seed_permissions, seed_roles
from app.models.menu import Menu

SEEDED_PATHS = {
    "/dashboard", "/profile", "/administration", "/users", "/roles",
    "/menus", "/appearance", "/settings", "/audit-logs",
}


async def _paths(db) -> set[str]:
    rows = (await db.execute(select(Menu))).scalars().all()
    return {m.path for m in rows if m.path}


async def _seeded_rows(db) -> list[Menu]:
    """Only the rows seed_menus owns.

    The suite shares a database file, so menus created by other tests —
    including an "Administration" that still uses the pre-v1.3 `.manage`
    slug — are visible here and would otherwise be blamed on the seed.
    """
    rows = (await db.execute(select(Menu))).scalars().all()
    return [m for m in rows if m.path in SEEDED_PATHS]


@pytest.mark.asyncio
async def test_seed_creates_the_default_menu(test_db):
    """An install with permissions but no menu is an install with no way in."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_menus(test_db)

    paths = await _paths(test_db)
    for expected in (
        "/dashboard",
        "/administration",
        "/users",
        "/roles",
        "/menus",
        "/appearance",
        "/settings",
        "/audit-logs",
    ):
        assert expected in paths, f"{expected} missing from the seeded menu"


@pytest.mark.asyncio
async def test_seeding_twice_does_not_duplicate(test_db):
    """Existing deployments already hold these rows; seed runs on every boot."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_menus(test_db)
    first = len((await test_db.execute(select(Menu))).scalars().all())

    await seed_menus(test_db)
    second = len((await test_db.execute(select(Menu))).scalars().all())

    assert second == first, f"seeding again added {second - first} row(s)"


@pytest.mark.asyncio
async def test_admin_children_hang_off_administration(test_db):
    """A flat list would lose the grouping the sidebar relies on."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_menus(test_db)

    rows = await _seeded_rows(test_db)
    parent = next(m for m in rows if m.path == "/administration")
    by_path = {m.path: m for m in rows}

    for child in ("/users", "/roles", "/menus", "/appearance", "/settings"):
        assert by_path[child].parent_id == parent.id, (
            f"{child} is not under /administration"
        )


@pytest.mark.asyncio
async def test_every_seeded_menu_points_at_a_real_permission(test_db):
    """A typo here hides the entry from everyone with no error anywhere —
    the gate simply never matches."""
    from app.models.rbac import Permission

    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_menus(test_db)

    known = {
        p.slug for p in (await test_db.execute(select(Permission))).scalars().all()
    }
    for menu in await _seeded_rows(test_db):
        if menu.required_permission:
            assert menu.required_permission in known, (
                f"{menu.label} requires unknown permission "
                f"{menu.required_permission!r}"
            )


@pytest.mark.asyncio
async def test_admin_entries_are_gated(test_db):
    """Without a required_permission an entry is public, so every visitor
    would be shown the admin console."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_menus(test_db)

    by_path = {m.path: m for m in await _seeded_rows(test_db)}
    for path, expected in (
        ("/users", "users.read"),
        ("/roles", "roles.read"),
        ("/menus", "menu.read"),
        ("/appearance", "settings.read"),
        ("/settings", "settings.read"),
        ("/audit-logs", "audit.read"),
    ):
        assert by_path[path].required_permission == expected, (
            f"{path} must be gated on {expected}, got "
            f"{by_path[path].required_permission!r}"
        )

    # Dashboard and Profile are deliberately open to any signed-in user.
    assert by_path["/dashboard"].required_permission is None
    assert by_path["/profile"].required_permission is None


@pytest.mark.asyncio
async def test_seeded_menu_uses_split_permissions_not_manage(test_db):
    """`menu.manage` predates the v1.3 CRUD split. A fresh install must not
    be born using the slug we are phasing out."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_menus(test_db)

    rows = await _seeded_rows(test_db)
    stale = [m.label for m in rows if (m.required_permission or "").endswith(".manage")]
    assert stale == [], f"seeded menu still uses .manage: {stale}"


@pytest.mark.asyncio
async def test_seed_repairs_an_install_that_only_has_categories(test_db):
    """The exact v1.4.0 state: the Categories migration inserted one row, so
    the sidebar's empty-table fallback no longer applied and the user saw a
    single entry."""
    import uuid

    test_db.add(
        Menu(
            id=uuid.uuid4(),
            label="Categories",
            path="/categories",
            icon="Tags",
            order_index=5,
            is_active=True,
            required_permission="category.read",
        )
    )
    await test_db.commit()

    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_menus(test_db)

    paths = await _paths(test_db)
    assert "/dashboard" in paths
    assert "/administration" in paths
    # And the pre-existing row is still there exactly once.
    rows = (await test_db.execute(select(Menu))).scalars().all()
    assert len([m for m in rows if m.path == "/categories"]) == 1
