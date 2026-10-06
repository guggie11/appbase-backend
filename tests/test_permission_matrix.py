"""A uniform RESOURCE x ACTION catalogue, without stranding existing grants.

Three modules shipped a single catch-all `.manage` permission, which made it
impossible to grant "view and edit menus, but never delete". Splitting it is
the point — but anyone already holding `.manage` must keep working, or an
upgrade silently removes their access.
"""
import pytest
from sqlalchemy import select

from app.core.seed import (
    MATRIX_ACTIONS,
    SEED_PERMISSIONS,
    matrix_rows,
    seed_permissions,
    seed_role_permissions,
    seed_roles,
)
from app.models.rbac import Permission, Role, RolePermission

# ---------------------------------------------------------------------------
# Uniform catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_managed_modules_gain_distinct_actions(test_db):
    """menu/settings/notifications had only read + manage."""
    await seed_permissions(test_db)
    rows = (await test_db.execute(select(Permission))).scalars().all()
    by_module: dict[str, set[str]] = {}
    for p in rows:
        by_module.setdefault(p.module, set()).add(p.action)

    for module in ("menu", "settings", "notifications"):
        actions = by_module[module]
        for needed in ("create", "update", "delete"):
            assert needed in actions, f"{module} still lacks {needed}: {sorted(actions)}"


@pytest.mark.asyncio
async def test_legacy_manage_permission_is_kept(test_db):
    """Deleting it would revoke access from everyone who holds it."""
    await seed_permissions(test_db)
    slugs = {
        p.slug for p in (await test_db.execute(select(Permission))).scalars().all()
    }
    assert "menu.manage" in slugs
    assert "settings.manage" in slugs


@pytest.mark.asyncio
async def test_every_permission_still_has_metadata(test_db):
    """The new rows must not arrive blank."""
    await seed_permissions(test_db)
    rows = (await test_db.execute(select(Permission))).scalars().all()
    bad = [p.slug for p in rows if not (p.description or "").strip() or not (p.group or "").strip()]
    assert bad == [], f"permissions missing description or group: {bad}"


@pytest.mark.asyncio
async def test_destructive_new_actions_are_flagged(test_db):
    await seed_permissions(test_db)
    rows = {
        p.slug: p for p in (await test_db.execute(select(Permission))).scalars().all()
    }
    assert rows["menu.delete"].is_dangerous is True
    assert rows["settings.delete"].is_dangerous is True
    assert rows["menu.read"].is_dangerous is False


# ---------------------------------------------------------------------------
# Matrix shape
# ---------------------------------------------------------------------------


def test_matrix_columns_match_the_design():
    assert MATRIX_ACTIONS == ["read", "create", "update", "delete", "approve"]


def test_matrix_rows_cover_every_module():
    rows = matrix_rows(SEED_PERMISSIONS)
    modules = {r["module"] for r in rows}
    for expected in ("users", "roles", "menu", "settings", "audit", "dashboard"):
        assert expected in modules, f"missing resource row: {expected}"


def test_matrix_marks_cells_that_do_not_apply():
    """A blank cell reads as "not ticked"; it must read as "not available"."""
    rows = {r["module"]: r for r in matrix_rows(SEED_PERMISSIONS)}

    # Dashboard is read-only — there is nothing to create or delete.
    dashboard = rows["dashboard"]
    assert dashboard["cells"]["read"]["available"] is True
    assert dashboard["cells"]["create"]["available"] is False
    assert dashboard["cells"]["delete"]["available"] is False

    # Users supports the full set.
    users = rows["users"]
    for action in ("read", "create", "update", "delete"):
        assert users["cells"][action]["available"] is True, action


def test_available_cells_carry_the_permission_slug():
    """Without the slug the UI cannot tell the backend what was ticked."""
    rows = {r["module"]: r for r in matrix_rows(SEED_PERMISSIONS)}
    assert rows["users"]["cells"]["read"]["slug"] == "users.read"
    assert rows["menu"]["cells"]["delete"]["slug"] == "menu.delete"
    assert rows["dashboard"]["cells"]["create"]["slug"] is None


def test_matrix_row_has_a_human_label():
    rows = {r["module"]: r for r in matrix_rows(SEED_PERMISSIONS)}
    assert rows["users"]["label"] == "User Management"
    assert rows["menu"]["label"] == "Menu Management"


# ---------------------------------------------------------------------------
# Granting a partial set — the whole reason for the split
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_grant_view_and_edit_without_delete(test_db, create_role):
    await seed_permissions(test_db)
    role = await create_role("menu-editor")

    wanted = ("menu.read", "menu.update")
    for slug in wanted:
        perm = (
            await test_db.execute(select(Permission).where(Permission.slug == slug))
        ).scalar_one()
        test_db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    await test_db.commit()

    held = {
        p.slug
        for p in (
            await test_db.execute(
                select(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        ).scalars().all()
    }
    assert held == set(wanted)
    assert "menu.delete" not in held, "delete leaked into a view+edit role"


@pytest.mark.asyncio
async def test_super_admin_receives_the_new_actions_too(test_db):
    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_role_permissions(test_db)

    role = (
        await test_db.execute(select(Role).where(Role.slug == "super-admin"))
    ).scalar_one()
    held = {
        p.slug
        for p in (
            await test_db.execute(
                select(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        ).scalars().all()
    }
    assert "menu.delete" in held
    assert len(held) == len(SEED_PERMISSIONS)
