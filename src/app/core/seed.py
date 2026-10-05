"""Seed data: default roles, permissions, and app settings."""
from sqlalchemy import select
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
]

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
    await db.commit()


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
    await db.commit()


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
