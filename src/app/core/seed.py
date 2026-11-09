"""Seed data: default roles, permissions, menu, and app settings."""
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rbac import Permission, Role, RolePermission

# group  -> which section of the permission matrix the row belongs to
# danger -> destructive; surfaced in red so it is not ticked casually
SEED_PERMISSIONS = [
    # ── Users ──
    {"slug": "users.read", "name": "View users", "module": "users", "action": "read",
     "group": "Users", "description": "View the user list and individual profiles."},
    {"slug": "users.create", "name": "Invite users", "module": "users", "action": "create",
     "group": "Users", "description": "Invite a new user and send the invitation email."},
    {"slug": "users.update", "name": "Edit users", "module": "users", "action": "update",
     "group": "Users", "description": "Change a user's name, email, or status."},
    {"slug": "users.delete", "name": "Delete users", "module": "users", "action": "delete",
     "group": "Users", "description": "Remove a user account.", "is_dangerous": True},
    {"slug": "users.assign_role", "name": "Assign roles to users", "module": "users", "action": "assign_role",
     "group": "Users", "description": "Grant or revoke a user's roles — changes what they can do."},

    # ── Roles & permissions ──
    {"slug": "roles.read", "name": "View roles", "module": "roles", "action": "read",
     "group": "Roles", "description": "View roles and the permissions attached to them."},
    {"slug": "roles.create", "name": "Create roles", "module": "roles", "action": "create",
     "group": "Roles", "description": "Define a new role."},
    {"slug": "roles.update", "name": "Edit roles", "module": "roles", "action": "update",
     "group": "Roles", "description": "Rename a role or change its description."},
    {"slug": "roles.delete", "name": "Delete roles", "module": "roles", "action": "delete",
     "group": "Roles", "description": "Remove a role; its holders lose those rights.",
     "is_dangerous": True},
    {"slug": "permissions.read", "name": "View permissions", "module": "permissions", "action": "read",
     "group": "Roles", "description": "View the full catalogue of permissions."},
    {"slug": "permissions.assign", "name": "Change role permissions", "module": "permissions", "action": "assign",
     "group": "Roles", "description": "Change which permissions a role grants.",
     "is_dangerous": True},

    # ── Navigation ──
    {"slug": "menu.read", "name": "View navigation", "module": "menu", "action": "read",
     "group": "Navigation", "description": "View the navigation menu structure."},
    {"slug": "menu.manage", "name": "Manage navigation", "module": "menu", "action": "manage",
     "group": "Navigation", "description": "Add, reorder, hide, or delete navigation items."},

    # ── Workspace ──
    {"slug": "dashboard.read", "name": "View dashboard", "module": "dashboard", "action": "read",
     "group": "Workspace", "description": "Open the dashboard and see its metrics."},
    {"slug": "profile.update", "name": "Edit own profile", "module": "profile", "action": "update",
     "group": "Workspace", "description": "Edit your own name, avatar, and password."},
    {"slug": "notifications.read", "name": "View own notifications", "module": "notifications", "action": "read",
     "group": "Workspace", "description": "See your own notifications."},
    {"slug": "notifications.manage", "name": "Send notifications", "module": "notifications", "action": "manage",
     "group": "Workspace", "description": "Send notifications and mark them for others."},

    # ── Platform ──
    {"slug": "audit.read", "name": "View audit log", "module": "audit", "action": "read",
     "group": "Platform", "description": "Read the immutable record of who changed what."},
    {"slug": "settings.read", "name": "View settings", "module": "settings", "action": "read",
     "group": "Platform", "description": "View application settings and appearance."},
    {"slug": "settings.manage", "name": "Change settings", "module": "settings", "action": "manage",
     "group": "Platform", "description": "Change app name, branding, colours, and limits."},
    # ── Navigation (split out of the former menu.manage) ──
    {"slug": "menu.create", "name": "Create navigation items", "module": "menu", "action": "create",
     "group": "Navigation", "description": "Add a new item to the navigation menu."},
    {"slug": "menu.update", "name": "Edit navigation items", "module": "menu", "action": "update",
     "group": "Navigation", "description": "Rename, reorder, or re-point an existing item."},
    {"slug": "menu.delete", "name": "Delete navigation items", "module": "menu", "action": "delete",
     "group": "Navigation", "description": "Remove an item and its children from the menu.",
     "is_dangerous": True},

    # ── Platform settings (split out of the former settings.manage) ──
    {"slug": "settings.create", "name": "Add settings", "module": "settings", "action": "create",
     "group": "Platform", "description": "Define a new application setting."},
    {"slug": "settings.update", "name": "Edit settings", "module": "settings", "action": "update",
     "group": "Platform", "description": "Change branding, limits, and other app settings."},
    {"slug": "settings.delete", "name": "Delete settings", "module": "settings", "action": "delete",
     "group": "Platform", "description": "Remove an application setting.", "is_dangerous": True},

    # ── Notifications (split out of the former notifications.manage) ──
    {"slug": "notifications.create", "name": "Send notifications", "module": "notifications", "action": "create",
     "group": "Workspace", "description": "Send a notification to other users."},
    {"slug": "notifications.update", "name": "Edit notifications", "module": "notifications", "action": "update",
     "group": "Workspace", "description": "Mark notifications read or amend them."},
    {"slug": "notifications.delete", "name": "Delete notifications", "module": "notifications", "action": "delete",
     "group": "Workspace", "description": "Remove notifications.", "is_dangerous": True},

    # ── Approval, the governance action the matrix exposes ──
    {"slug": "users.approve", "name": "Approve user requests", "module": "users", "action": "approve",
     "group": "Users", "description": "Approve pending accounts and access requests."},
    {"slug": "settings.approve", "name": "Approve setting changes", "module": "settings", "action": "approve",
     "group": "Platform", "description": "Sign off changes that need a second pair of eyes."},
    # ── Reference data ──
    {"slug": "category.read", "name": "View categories", "module": "category", "action": "read",
     "group": "Reference Data", "description": "See category groups and their items."},
    {"slug": "category.create", "name": "Create categories", "module": "category", "action": "create",
     "group": "Reference Data", "description": "Add a category group or an item inside one."},
    {"slug": "category.update", "name": "Edit categories", "module": "category", "action": "update",
     "group": "Reference Data", "description": "Rename, reorder, deprecate, or restore an item."},
    {"slug": "category.delete", "name": "Delete categories", "module": "category", "action": "delete",
     "group": "Reference Data", "description": "Remove a category that nothing references.",
     "is_dangerous": True},
]


# Columns of the Roles & Permissions matrix, in display order.
MATRIX_ACTIONS = ["read", "create", "update", "delete", "approve"]

# Human labels for the resource rows. A module without an entry falls back to
# its slug, so adding a module never makes it vanish from the matrix.
MODULE_LABELS = {
    "users": "User Management",
    "roles": "Roles & Permissions",
    "permissions": "Permission Catalogue",
    "menu": "Menu Management",
    "settings": "Settings",
    "notifications": "Notifications",
    "category": "Reference Data",
    "audit": "Audit Log",
    "dashboard": "Dashboard",
    "profile": "Profile",
}

# Order the rows so the resources an admin touches most sit at the top.
MODULE_ORDER = [
    "users", "roles", "permissions", "menu",
    "settings", "notifications", "category", "audit", "dashboard", "profile",
]


def matrix_rows(permissions: list[dict] | None = None) -> list[dict]:
    """Build the RESOURCE x ACTION grid from the permission catalogue.

    Every cell reports whether the action exists for that resource. A cell
    that does not apply must be rendered as unavailable rather than left
    blank — an empty checkbox reads as "not granted yet", which is a
    different and misleading claim.
    """
    rows_src = permissions if permissions is not None else SEED_PERMISSIONS

    by_module: dict[str, dict[str, str]] = {}
    for p in rows_src:
        by_module.setdefault(p["module"], {})[p["action"]] = p["slug"]

    def rank(module: str) -> int:
        return MODULE_ORDER.index(module) if module in MODULE_ORDER else len(MODULE_ORDER)

    out: list[dict] = []
    for module in sorted(by_module, key=lambda m: (rank(m), m)):
        actions = by_module[module]
        cells = {
            action: {
                "available": action in actions,
                "slug": actions.get(action),
            }
            for action in MATRIX_ACTIONS
        }
        out.append(
            {
                "module": module,
                "label": MODULE_LABELS.get(module, module.replace("_", " ").title()),
                "cells": cells,
                # Slugs that exist for this module but have no column of their
                # own (menu.manage, permissions.assign, ...). Hiding them would
                # silently drop granted rights from the UI.
                "extra": sorted(
                    slug for action, slug in actions.items()
                    if action not in MATRIX_ACTIONS
                ),
            }
        )
    return out


SEED_ROLES = [
    {"name": "Super Admin", "slug": "super-admin", "description": "Full system access",
     "is_system": True, "kind": "platform"},
    {"name": "User", "slug": "user", "description": "Standard user",
     "is_system": True, "kind": "built-in"},
]

# What a standard user may do: their own workspace, nothing administrative.
USER_ROLE_PERMISSIONS = [
    "dashboard.read",
    "profile.update",
    "notifications.read",
]

SEED_SETTINGS = [
    {"key": "app_name", "value": "Appbase", "type": "string", "is_public": True, "is_secret": False},
    {"key": "app_version", "value": "1.0.0", "type": "string", "is_public": True, "is_secret": False},
    {"key": "max_login_attempts", "value": "5", "type": "number", "is_public": False, "is_secret": False},
    {"key": "lockout_duration_minutes", "value": "15", "type": "number", "is_public": False, "is_secret": False},
    {"key": "smtp_host", "value": "localhost", "type": "string", "is_public": False, "is_secret": True},
    # Phase 5: App Appearance Settings
    {"key": "app_subtitle", "value": "App Template", "type": "string", "is_public": True, "is_secret": False},
    {"key": "primary_color", "value": "#D94F3D", "type": "string", "is_public": True, "is_secret": False},
    {"key": "logo_url", "value": "", "type": "string", "is_public": True, "is_secret": False},
    {"key": "favicon_url", "value": "", "type": "string", "is_public": True, "is_secret": False},
]


async def seed_permissions(db: AsyncSession) -> None:
    """Insert missing permissions and backfill metadata on existing ones.

    Existing deployments already hold the 20 slugs without description, group,
    or danger flag, so an insert-only seed would leave them blank forever.
    """
    for pdata in SEED_PERMISSIONS:
        result = await db.execute(select(Permission).where(Permission.slug == pdata["slug"]))
        existing = result.scalar_one_or_none()
        if existing:
            # Keep the label in sync too: renaming a permission in SEED_PERMISSIONS
            # otherwise never reaches a deployment that already has the row.
            existing.name = pdata["name"]
            existing.description = pdata.get("description")
            existing.group = pdata.get("group")
            existing.is_dangerous = pdata.get("is_dangerous", False)
        else:
            db.add(Permission(**pdata))
        # Commit per row: with several workers starting together, a clash on
        # one slug would otherwise discard every other row in the batch.
        try:
            await db.commit()
        except IntegrityError:
            # Another worker inserted it first — that is the desired state.
            await db.rollback()


async def seed_roles(db: AsyncSession) -> None:
    for rdata in SEED_ROLES:
        result = await db.execute(select(Role).where(Role.slug == rdata["slug"]))
        existing = result.scalar_one_or_none()
        if existing:
            # Backfill: roles created before `kind` existed default to custom,
            # which would leave the platform role unprotected.
            existing.kind = rdata["kind"]
        else:
            db.add(Role(**rdata))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def seed_role_permissions(db: AsyncSession) -> None:
    """Attach permissions to the seeded roles.

    Previously the seed created permissions and roles but never linked them:
    Super Admin held zero rights and only worked because of a hard-coded
    bypass, while any ordinary role could never be granted anything.

    Idempotent — the seed runs on every startup.
    """
    perms = {p.slug: p for p in (await db.execute(select(Permission))).scalars().all()}
    roles = {r.slug: r for r in (await db.execute(select(Role))).scalars().all()}

    wanted: dict[str, list[str]] = {
        "super-admin": list(perms.keys()),
        "user": USER_ROLE_PERMISSIONS,
    }

    for role_slug, slugs in wanted.items():
        role = roles.get(role_slug)
        if role is None:
            continue

        existing = {
            rp.permission_id
            for rp in (
                await db.execute(
                    select(RolePermission).where(RolePermission.role_id == role.id)
                )
            ).scalars().all()
        }

        for slug in slugs:
            perm = perms.get(slug)
            if perm is not None and perm.id not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await db.commit()


async def seed_settings(db: AsyncSession) -> None:
    from app.models.audit import AppSetting

    for sdata in SEED_SETTINGS:
        result = await db.execute(select(AppSetting).where(AppSetting.key == sdata["key"]))
        existing = result.scalar_one_or_none()
        if not existing:
            import uuid
            setting = AppSetting(id=uuid.uuid4(), **sdata)
            db.add(setting)
    await db.commit()


# ---------------------------------------------------------------------------
# Default menu
# ---------------------------------------------------------------------------
# A fresh install used to receive no menu at all: the rows were created by
# hand on staging, so nobody noticed until a clean clone of v1.4.0 logged in
# and found a single entry. Permissions without a way to reach them are not
# an application.
#
# `parent` refers to another entry's path; order follows the sidebar.
SEED_MENUS = [
    {"label": "Dashboard", "path": "/dashboard", "icon": "LayoutDashboard",
     "parent": None, "order_index": 0, "required_permission": None},
    {"label": "Profile", "path": "/profile", "icon": "User",
     "parent": None, "order_index": 1, "required_permission": None},
    {"label": "Administration", "path": "/administration", "icon": "ShieldCheck",
     "parent": None, "order_index": 2, "required_permission": None},
    {"label": "Users", "path": "/users", "icon": "Users",
     "parent": "/administration", "order_index": 1, "required_permission": "users.read"},
    {"label": "Roles & Permissions", "path": "/roles", "icon": "Shield",
     "parent": "/administration", "order_index": 2, "required_permission": "roles.read"},
    # menu.read, not menu.manage: the catch-all was split into CRUD in v1.3
    # and a new install should not be born using the slug being phased out.
    {"label": "Menu Management", "path": "/menus", "icon": "Menu",
     "parent": "/administration", "order_index": 3, "required_permission": "menu.read"},
    {"label": "Appearance", "path": "/appearance", "icon": "Palette",
     "parent": "/administration", "order_index": 4, "required_permission": "settings.read"},
    {"label": "Settings", "path": "/settings", "icon": "Settings",
     "parent": "/administration", "order_index": 5, "required_permission": "settings.read"},
    {"label": "Audit Log", "path": "/audit-logs", "icon": "ClipboardList",
     "parent": "/administration", "order_index": 6, "required_permission": "audit.read"},
]


async def seed_menus(db: AsyncSession) -> None:
    """Create the default menu, matching on path so it never duplicates.

    Runs on every boot and on existing deployments that already hold these
    rows, so an insert-only pass would double them.
    """
    from app.models.menu import Menu

    existing = {
        m.path: m
        for m in (await db.execute(select(Menu))).scalars().all()
        if m.path
    }

    # Parents first: a child cannot reference an id that does not exist yet.
    for entry in sorted(SEED_MENUS, key=lambda e: e["parent"] is not None):
        if entry["path"] in existing:
            continue

        parent_id = None
        if entry["parent"]:
            parent = existing.get(entry["parent"])
            if parent is None:
                # Parent missing and not seeded either — skip rather than
                # silently promote this entry to the top level.
                continue
            parent_id = parent.id

        menu = Menu(
            id=uuid.uuid4(),
            label=entry["label"],
            path=entry["path"],
            icon=entry["icon"],
            parent_id=parent_id,
            order_index=entry["order_index"],
            is_active=True,
            required_permission=entry["required_permission"],
        )
        db.add(menu)
        try:
            await db.commit()
            await db.refresh(menu)
            existing[entry["path"]] = menu
        except IntegrityError:
            # Another worker inserted it first — the desired state either way.
            await db.rollback()
            found = (
                await db.execute(select(Menu).where(Menu.path == entry["path"]))
            ).scalar_one_or_none()
            if found is not None:
                existing[entry["path"]] = found
