"""Permission metadata, role kinds, and the seed that actually grants rights.

Before v1.2a the seed created 20 permissions but never attached them to any
role: Super Admin held zero. Nothing broke only because the backend hard-codes
a super-admin bypass in four places — which meant an ordinary role could never
be granted anything through seeding.
"""
import pytest
from sqlalchemy import select

from app.core.seed import SEED_PERMISSIONS, seed_permissions, seed_role_permissions, seed_roles
from app.models.rbac import Permission, Role, RolePermission

# --------------------------------------------------------------------------
# Permission metadata
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_seed_permission_has_a_description(test_db):
    """A bare slug like "menu.manage" tells an admin nothing."""
    await seed_permissions(test_db)

    rows = (await test_db.execute(select(Permission))).scalars().all()
    missing = [p.slug for p in rows if not (p.description or "").strip()]
    assert missing == [], f"permissions without a description: {missing}"


@pytest.mark.asyncio
async def test_reseeding_updates_a_renamed_label(test_db):
    """Backfill must cover the label, not only the new columns.

    Renaming "Read Users" to "View users" in SEED_PERMISSIONS never reached
    staging, because the update branch refreshed description/group but left
    `name` untouched — so the old CRUD wording stayed on screen.
    """
    await seed_permissions(test_db)

    row = (
        await test_db.execute(select(Permission).where(Permission.slug == "users.read"))
    ).scalar_one()
    row.name = "Stale Label"
    await test_db.commit()

    await seed_permissions(test_db)

    refreshed = (
        await test_db.execute(select(Permission).where(Permission.slug == "users.read"))
    ).scalar_one()
    await test_db.refresh(refreshed)
    assert refreshed.name != "Stale Label", "reseeding did not refresh the label"


@pytest.mark.asyncio
async def test_every_seed_permission_has_a_group(test_db):
    """Grouping is what turns 20 flat rows into a readable matrix."""
    await seed_permissions(test_db)

    rows = (await test_db.execute(select(Permission))).scalars().all()
    missing = [p.slug for p in rows if not (p.group or "").strip()]
    assert missing == [], f"permissions without a group: {missing}"


@pytest.mark.asyncio
async def test_destructive_permissions_are_flagged(test_db):
    """Deleting data must be visibly riskier than reading it."""
    await seed_permissions(test_db)

    rows = {p.slug: p for p in (await test_db.execute(select(Permission))).scalars().all()}

    assert rows["users.delete"].is_dangerous is True
    assert rows["roles.delete"].is_dangerous is True
    assert rows["users.read"].is_dangerous is False


# --------------------------------------------------------------------------
# Role kinds
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_roles_carry_a_kind(test_db):
    await seed_roles(test_db)

    roles = {r.slug: r for r in (await test_db.execute(select(Role))).scalars().all()}

    assert roles["super-admin"].kind == "platform"
    assert roles["user"].kind == "built-in"


@pytest.mark.asyncio
async def test_new_roles_default_to_custom(test_db, create_role):
    role = await create_role("analyst")
    assert role.kind == "custom"


# --------------------------------------------------------------------------
# The blocker: seeding must actually grant permissions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_super_admin_is_granted_every_permission(test_db):
    """The exact gap found in production: Super Admin held zero rights."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_role_permissions(test_db)

    role = (
        await test_db.execute(select(Role).where(Role.slug == "super-admin"))
    ).scalar_one()
    granted = (
        await test_db.execute(
            select(RolePermission).where(RolePermission.role_id == role.id)
        )
    ).scalars().all()

    assert len(granted) == len(SEED_PERMISSIONS), (
        f"super-admin has {len(granted)} of {len(SEED_PERMISSIONS)} permissions"
    )


@pytest.mark.asyncio
async def test_standard_user_role_gets_a_sensible_subset(test_db):
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_role_permissions(test_db)

    role = (await test_db.execute(select(Role).where(Role.slug == "user"))).scalar_one()
    rows = (
        await test_db.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        )
    ).scalars().all()
    slugs = {p.slug for p in rows}

    assert "profile.update" in slugs, "a user must be able to edit their own profile"
    assert "dashboard.read" in slugs
    # A standard user must not administer the platform.
    assert "users.delete" not in slugs
    assert "roles.update" not in slugs


@pytest.mark.asyncio
async def test_seeding_twice_does_not_duplicate_grants(test_db):
    """Seed runs on every startup, so it has to be idempotent."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_role_permissions(test_db)
    await seed_role_permissions(test_db)

    role = (
        await test_db.execute(select(Role).where(Role.slug == "super-admin"))
    ).scalar_one()
    granted = (
        await test_db.execute(
            select(RolePermission).where(RolePermission.role_id == role.id)
        )
    ).scalars().all()

    assert len(granted) == len(SEED_PERMISSIONS), "duplicate grants after reseeding"
