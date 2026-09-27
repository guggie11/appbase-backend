"""Seed data: default roles and permissions."""
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
]

SEED_ROLES = [
    {"name": "Super Admin", "slug": "super-admin", "description": "Full system access", "is_system": True},
    {"name": "User", "slug": "user", "description": "Standard user", "is_system": True},
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
