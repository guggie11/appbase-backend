"""Creating the very first administrator.

A fresh clone seeds permissions, roles, and settings but no user at all, so
nobody can log in: the application is locked out of itself. This covers the
script that opens the door.
"""
import pytest
from scripts.create_superadmin import create_superadmin
from sqlalchemy import delete, select

from app.core.seed import seed_permissions, seed_roles
from app.models.rbac import Role, UserRole
from app.models.user import User


@pytest.mark.asyncio
async def test_creates_a_user_that_can_be_found(test_db):
    await seed_permissions(test_db)
    await seed_roles(test_db)

    await create_superadmin(test_db, "boss@example.com", "Str0ng@Pass1", "Boss")

    user = (
        await test_db.execute(select(User).where(User.email == "boss@example.com"))
    ).scalar_one_or_none()
    assert user is not None


@pytest.mark.asyncio
async def test_the_new_user_holds_the_super_admin_role(test_db):
    """A user without the role is as useless as no user at all."""
    await seed_permissions(test_db)
    await seed_roles(test_db)

    await create_superadmin(test_db, "boss2@example.com", "Str0ng@Pass1", "Boss")

    user = (
        await test_db.execute(select(User).where(User.email == "boss2@example.com"))
    ).scalar_one()
    role = (
        await test_db.execute(select(Role).where(Role.slug == "super-admin"))
    ).scalar_one()
    link = (
        await test_db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            )
        )
    ).scalar_one_or_none()
    assert link is not None, "super admin role was not attached"


@pytest.mark.asyncio
async def test_password_is_hashed_not_stored_raw(test_db):
    await seed_permissions(test_db)
    await seed_roles(test_db)

    await create_superadmin(test_db, "boss3@example.com", "Str0ng@Pass1", "Boss")

    user = (
        await test_db.execute(select(User).where(User.email == "boss3@example.com"))
    ).scalar_one()
    assert user.password_hash != "Str0ng@Pass1"
    assert "Str0ng@Pass1" not in (user.password_hash or "")


@pytest.mark.asyncio
async def test_the_account_is_usable_immediately(test_db):
    """An unverified or inactive first admin cannot log in either."""
    await seed_permissions(test_db)
    await seed_roles(test_db)

    await create_superadmin(test_db, "boss4@example.com", "Str0ng@Pass1", "Boss")

    user = (
        await test_db.execute(select(User).where(User.email == "boss4@example.com"))
    ).scalar_one()
    assert user.status == "active"
    assert user.is_verified is True


@pytest.mark.asyncio
async def test_running_it_twice_does_not_fail_or_duplicate(test_db):
    """Re-running setup is normal; a crash on the second run is not."""
    await seed_permissions(test_db)
    await seed_roles(test_db)

    await create_superadmin(test_db, "boss5@example.com", "Str0ng@Pass1", "Boss")
    await create_superadmin(test_db, "boss5@example.com", "Str0ng@Pass1", "Boss")

    rows = (
        await test_db.execute(select(User).where(User.email == "boss5@example.com"))
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_refuses_to_run_without_the_super_admin_role(test_db):
    """Silently creating a role-less admin would look like success."""
    # The suite shares a database, so the role may already be seeded by
    # another test. Remove it to recreate a genuinely fresh install.
    role = (
        await test_db.execute(select(Role).where(Role.slug == "super-admin"))
    ).scalar_one_or_none()
    if role is not None:
        await test_db.execute(delete(UserRole).where(UserRole.role_id == role.id))
        await test_db.delete(role)
        await test_db.commit()

    with pytest.raises(RuntimeError, match="super-admin"):
        await create_superadmin(test_db, "boss6@example.com", "Str0ng@Pass1", "Boss")


@pytest.mark.asyncio
async def test_rejects_a_weak_password(test_db):
    """The first account is the most privileged one in the system."""
    await seed_permissions(test_db)
    await seed_roles(test_db)

    with pytest.raises(ValueError):
        await create_superadmin(test_db, "boss7@example.com", "short", "Boss")
