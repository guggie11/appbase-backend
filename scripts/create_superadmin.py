#!/usr/bin/env python
"""Create the first super administrator.

A fresh install seeds permissions, roles, and settings but no user, so there
is nobody to log in as. Run this once after the first migration:

    docker compose exec app uv run python scripts/create_superadmin.py \
        --email admin@example.com --password 'Str0ng@Pass1' --name 'Admin'

Credentials may also come from SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD /
SUPERADMIN_NAME. Nothing is hardcoded: a default password shipped in a public
template would be the same on every install that forgot to change it.

Safe to run twice — an existing account is left alone.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Allow running as `python scripts/create_superadmin.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.models.rbac import Role, UserRole  # noqa: E402
from app.models.user import User  # noqa: E402

MIN_PASSWORD_LENGTH = 12
SUPER_ADMIN_SLUG = "super-admin"


async def create_superadmin(
    db: AsyncSession,
    email: str,
    password: str,
    name: str = "Super Admin",
    seed_if_missing: bool = False,
) -> User:
    """Create (or reuse) the first super administrator.

    Args:
        seed_if_missing: seed roles and permissions when they are absent.
            The documented setup order starts the app before the tables
            exist, so startup seeding fails against an empty database and is
            never retried — leaving nothing to grant.

    Raises:
        ValueError: the password is too weak for the most privileged account.
        RuntimeError: roles are absent and seeding was not requested, so the
            account could not be granted anything — creating it anyway would
            look like success.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters; "
            "this account has full system access"
        )

    role = (
        await db.execute(select(Role).where(Role.slug == SUPER_ADMIN_SLUG))
    ).scalar_one_or_none()

    if role is None and seed_if_missing:
        from app.core.seed import (
            seed_permissions,
            seed_role_permissions,
            seed_roles,
            seed_settings,
        )

        await seed_permissions(db)
        await seed_roles(db)
        await seed_role_permissions(db)
        await seed_settings(db)
        role = (
            await db.execute(select(Role).where(Role.slug == SUPER_ADMIN_SLUG))
        ).scalar_one_or_none()

    if role is None:
        raise RuntimeError(
            f"role '{SUPER_ADMIN_SLUG}' not found — run the migrations first, "
            "or pass --seed to create roles and permissions now"
        )

    existing = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if existing is None:
        user = User(
            id=uuid.uuid4(),
            name=name,
            email=email,
            password_hash=hash_password(password),
            status="active",
            is_verified=True,
        )
        db.add(user)
        await db.flush()
    else:
        # Re-running setup is normal. Leave the account alone but make sure
        # it is usable, so a half-finished first attempt can be completed.
        user = existing
        user.status = "active"
        user.is_verified = True

    link = (
        await db.execute(
            select(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            )
        )
    ).scalar_one_or_none()
    if link is None:
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await db.commit()
    return user


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=os.getenv("SUPERADMIN_EMAIL"))
    parser.add_argument("--password", default=os.getenv("SUPERADMIN_PASSWORD"))
    parser.add_argument(
        "--name", default=os.getenv("SUPERADMIN_NAME", "Super Admin")
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="seed roles and permissions first if the database has none",
    )
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.email or not args.password:
        print(
            "error: email and password are required.\n"
            "  scripts/create_superadmin.py --email you@example.com "
            "--password 'Str0ng@Pass1'\n"
            "or set SUPERADMIN_EMAIL and SUPERADMIN_PASSWORD.",
            file=sys.stderr,
        )
        return 2

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            user = await create_superadmin(
                db, args.email, args.password, args.name,
                seed_if_missing=args.seed,
            )
        except (ValueError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    print(f"super administrator ready: {user.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
