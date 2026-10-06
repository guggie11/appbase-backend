"""Bulk operations on users.

Changing twenty users one modal at a time is the problem. The danger is that
one careless batch removes the operator's own access, leaving nobody able to
undo it — so every bulk path refuses to touch the caller.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.rbac import Role, UserRole
from app.models.user import User

PLATFORM_KIND = "platform"


async def _existing_user_ids(db: AsyncSession, user_ids: list[uuid.UUID]) -> set:
    """Ids that actually resolve to a live user.

    A stale id in a list of twenty must not abort the other nineteen.
    """
    if not user_ids:
        return set()
    rows = await db.execute(
        select(User.id).where(User.id.in_(user_ids), User.deleted_at.is_(None))
    )
    return {row[0] for row in rows.fetchall()}


def _reject_self(caller_id: uuid.UUID, user_ids: list[uuid.UUID], what: str) -> None:
    if caller_id in user_ids:
        raise AppException(
            code="USERS_CANNOT_BULK_MODIFY_SELF",
            message=f"Tidak dapat {what} akun sendiri lewat aksi massal",
            status_code=400,
        )


async def bulk_assign_roles(
    db: AsyncSession,
    caller_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    role_ids: list[uuid.UUID],
    action: str,
) -> dict:
    if action not in ("add", "remove"):
        raise AppException(
            code="USERS_INVALID_BULK_ACTION",
            message="Action harus 'add' atau 'remove'",
            status_code=400,
        )

    if action == "remove":
        # Stripping your own rights is the one mistake with no way back.
        _reject_self(caller_id, user_ids, "mencabut role")

    valid_ids = await _existing_user_ids(db, user_ids)
    skipped = len(set(user_ids)) - len(valid_ids)

    roles = (
        await db.execute(select(Role).where(Role.id.in_(role_ids)))
    ).scalars().all()
    if len(roles) != len(set(role_ids)):
        raise AppException(
            code="ROLES_NOT_FOUND",
            message="Sebagian role tidak ditemukan",
            status_code=404,
        )

    if action == "remove":
        await _guard_last_platform_holder(db, valid_ids, roles)

    existing_pairs = {
        (r.user_id, r.role_id)
        for r in (
            await db.execute(
                select(UserRole).where(
                    UserRole.user_id.in_(valid_ids),
                    UserRole.role_id.in_(role_ids),
                )
            )
        ).scalars().all()
    }

    touched = set()
    for user_id in valid_ids:
        for role in roles:
            pair = (user_id, role.id)
            if action == "add":
                # Idempotent: the same batch run twice must not duplicate rows.
                if pair not in existing_pairs:
                    db.add(UserRole(user_id=user_id, role_id=role.id))
                    touched.add(user_id)
            elif pair in existing_pairs:
                row = (
                    await db.execute(
                        select(UserRole).where(
                            UserRole.user_id == user_id, UserRole.role_id == role.id
                        )
                    )
                ).scalar_one()
                await db.delete(row)
                touched.add(user_id)

    await db.commit()
    return {"updated": len(valid_ids), "changed": len(touched), "skipped": skipped}


async def _guard_last_platform_holder(db: AsyncSession, user_ids: set, roles) -> None:
    """Never leave a platform role with nobody holding it."""
    for role in roles:
        if getattr(role, "kind", "custom") != PLATFORM_KIND:
            continue
        total = (
            await db.execute(
                select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
            )
        ).scalar_one()
        losing = (
            await db.execute(
                select(func.count())
                .select_from(UserRole)
                .where(UserRole.role_id == role.id, UserRole.user_id.in_(user_ids))
            )
        ).scalar_one()
        if total - losing < 1:
            raise AppException(
                code="USERS_LAST_PLATFORM_ADMIN",
                message=f"Role {role.name} harus tetap dimiliki minimal satu user",
                status_code=400,
            )


async def bulk_update_status(
    db: AsyncSession,
    caller_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    status: str,
) -> dict:
    if status not in ("active", "inactive", "pending"):
        raise AppException(
            code="USERS_INVALID_STATUS",
            message="Status tidak valid",
            status_code=400,
        )

    if status != "active":
        # Deactivating yourself is a lockout nobody can undo.
        _reject_self(caller_id, user_ids, "menonaktifkan")

    valid_ids = await _existing_user_ids(db, user_ids)
    skipped = len(set(user_ids)) - len(valid_ids)

    rows = (
        await db.execute(select(User).where(User.id.in_(valid_ids)))
    ).scalars().all()
    for user in rows:
        user.status = status

    await db.commit()
    return {"updated": len(rows), "skipped": skipped}
