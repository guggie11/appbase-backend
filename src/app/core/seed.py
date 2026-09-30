"""Seed data: default roles, permissions, and app settings."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rbac import Permission, Role

SEED_PERMISSIONS = [
    {"slug": "users.read", "name": "Read Users", "module": "users", "action": "read"},
    {"slug": "users.create", "name": "Create Users", "module": "users", "action": "create"},
    {"slug": "users.update", "name": "Update Users", "module": "users", "action": "update"},
    {"slug": "users.delete", "name": "Delete Users", "module": "users", "action": "delete"},
    {"slug": "users.assign_role", "name": "Assign Role to Users", "module": "users", "action": "assign_role"},
    {"slug": "roles.read", "name": "Read Roles", "module": "roles", "action": "read"},
    {"slug": "roles.create", "name": "Create Roles", "module": "roles", "action": "create"},
    {"slug": "roles.update", "name": "Update Roles", "module": "roles", "action": "update"},
    {"slug": "roles.delete", "name": "Delete Roles", "module": "roles", "action": "delete"},
    {"slug": "permissions.read", "name": "Read Permissions", "module": "permissions", "action": "read"},
    {"slug": "permissions.assign", "name": "Assign Permissions", "module": "permissions", "action": "assign"},
    # Phase 3: Menu Management
    {"slug": "menu.read", "name": "Read Menus", "module": "menu", "action": "read"},
    {"slug": "menu.manage", "name": "Manage Menus", "module": "menu", "action": "manage"},
    # Phase 3: Dashboard
    {"slug": "dashboard.read", "name": "Read Dashboard", "module": "dashboard", "action": "read"},
    # Phase 4: Audit Log, Settings, Profile
    {"slug": "audit.read", "name": "Read Audit Logs", "module": "audit", "action": "read"},
    {"slug": "settings.read", "name": "Read Settings", "module": "settings", "action": "read"},
    {"slug": "settings.manage", "name": "Manage Settings", "module": "settings", "action": "manage"},
    {"slug": "profile.update", "name": "Update Profile", "module": "profile", "action": "update"},
    # C1: Notifications
    {"slug": "notifications.read", "name": "Read Notifications", "module": "notifications", "action": "read"},
    {"slug": "notifications.manage", "name": "Manage Notifications", "module": "notifications", "action": "manage"},
]

SEED_ROLES = [
    {"name": "Super Admin", "slug": "super-admin", "description": "Full system access", "is_system": True},
    {"name": "User", "slug": "user", "description": "Standard user", "is_system": True},
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
    for pdata in SEED_PERMISSIONS:
        result = await db.execute(select(Permission).where(Permission.slug == pdata["slug"]))
        existing = result.scalar_one_or_none()
        if not existing:
            perm = Permission(**pdata)
            db.add(perm)
    await db.commit()


async def seed_roles(db: AsyncSession) -> None:
    for rdata in SEED_ROLES:
        result = await db.execute(select(Role).where(Role.slug == rdata["slug"]))
        existing = result.scalar_one_or_none()
        if not existing:
            role = Role(**rdata)
            db.add(role)
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
