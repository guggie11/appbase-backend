"""User management business logic service."""
import os
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.models.rbac import Role, UserRole
from app.models.token import RefreshToken
from app.models.user import User, UserInvitation


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_user_with_roles(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.user_roles).selectinload(UserRole.role)
        )
        .where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(code="USERS_NOT_FOUND", message="User tidak ditemukan", status_code=404)
    return user


async def list_users(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 10,
    search: str | None = None,
    status: str | None = None,
    role_id: uuid.UUID | None = None,
) -> tuple[list[User], int]:
    query = (
        select(User)
        .options(selectinload(User.user_roles).selectinload(UserRole.role))
        .where(User.deleted_at.is_(None))
    )
    count_query = select(func.count()).select_from(User).where(User.deleted_at.is_(None))

    if search:
        ilike_expr = f"%{search}%"
        query = query.where(or_(User.name.ilike(ilike_expr), User.email.ilike(ilike_expr)))
        count_query = count_query.where(or_(User.name.ilike(ilike_expr), User.email.ilike(ilike_expr)))

    if status:
        query = query.where(User.status == status)
        count_query = count_query.where(User.status == status)

    if role_id:
        query = query.join(UserRole, UserRole.user_id == User.id).where(UserRole.role_id == role_id)
        count_query = count_query.join(UserRole, UserRole.user_id == User.id).where(UserRole.role_id == role_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()
    return list(users), total


async def create_user(
    db: AsyncSession,
    name: str,
    email: str,
    role_ids: list[uuid.UUID],
) -> tuple[User, str]:
    # Check email uniqueness
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise AppException(code="USERS_EMAIL_ALREADY_EXISTS", message="Email sudah terdaftar", status_code=409)

    user = User(
        id=uuid.uuid4(),
        name=name,
        email=email,
        status="pending",
        is_verified=False,
        password_hash=None,
    )
    db.add(user)
    await db.flush()

    # Assign roles
    for rid in role_ids:
        role_res = await db.execute(select(Role).where(Role.id == rid))
        role = role_res.scalar_one_or_none()
        if not role:
            raise AppException(code="ROLES_NOT_FOUND", message=f"Role {rid} tidak ditemukan", status_code=404)
        ur = UserRole(user_id=user.id, role_id=rid)
        db.add(ur)

    # Generate invitation token
    raw_token = os.urandom(32).hex()
    token_hash = sha256(raw_token.encode()).hexdigest()
    invitation = UserInvitation(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=_now() + timedelta(days=7),
    )
    db.add(invitation)

    await db.commit()
    return await _get_user_with_roles(db, user.id), raw_token


async def update_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str | None = None,
    email: str | None = None,
) -> User:
    user = await _get_user_with_roles(db, user_id)

    if name is not None:
        user.name = name

    if email is not None and email != user.email:
        # Check uniqueness
        result = await db.execute(select(User).where(User.email == email, User.id != user_id))
        if result.scalar_one_or_none():
            raise AppException(code="USERS_EMAIL_ALREADY_EXISTS", message="Email sudah digunakan", status_code=409)
        user.email = email

    await db.commit()
    return await _get_user_with_roles(db, user_id)


async def delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    user = await _get_user_with_roles(db, user_id)

    # Check if super-admin
    for ur in user.user_roles:
        if ur.role.slug == "super-admin":
            raise AppException(
                code="USERS_CANNOT_DELETE_SUPER_ADMIN",
                message="Super admin tidak dapat dihapus",
                status_code=400,
            )

    # Soft delete
    user.deleted_at = _now()

    # Revoke all refresh tokens
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )

    await db.commit()


async def update_status(db: AsyncSession, user_id: uuid.UUID, status: str) -> User:
    user = await _get_user_with_roles(db, user_id)

    # Reject changing super admin status
    for ur in user.user_roles:
        if ur.role.slug == "super-admin":
            raise AppException(
                code="USERS_CANNOT_CHANGE_SUPER_ADMIN_STATUS",
                message="Status super admin tidak dapat diubah",
                status_code=400,
            )

    valid_statuses = {"pending", "active", "inactive", "suspended"}
    if status not in valid_statuses:
        raise AppException(code="VALIDATION_ERROR", message=f"Status tidak valid: {status}", status_code=400)

    user.status = status
    await db.commit()
    return await _get_user_with_roles(db, user_id)


async def assign_roles(db: AsyncSession, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> User:
    # Verify user exists (raises USERS_NOT_FOUND if not)
    await _get_user_with_roles(db, user_id)
    for rid in role_ids:
        role_res = await db.execute(select(Role).where(Role.id == rid))
        role = role_res.scalar_one_or_none()
        if not role:
            raise AppException(code="ROLES_NOT_FOUND", message=f"Role {rid} tidak ditemukan", status_code=404)

    # Remove existing user_roles
    existing_urs = await db.execute(select(UserRole).where(UserRole.user_id == user_id))
    for ur in existing_urs.scalars().all():
        await db.delete(ur)

    # Add new user_roles
    for rid in role_ids:
        ur = UserRole(user_id=user_id, role_id=rid)
        db.add(ur)

    await db.commit()
    return await _get_user_with_roles(db, user_id)


async def upload_avatar(
    db: AsyncSession,
    user_id: uuid.UUID,
    file_data: bytes,
    ext: str,
) -> User:
    user = await _get_user_with_roles(db, user_id)

    # Ensure directory exists
    avatar_dir = Path("static/avatars")
    avatar_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{user_id}.{ext}"
    filepath = avatar_dir / filename

    with open(filepath, "wb") as f:
        f.write(file_data)

    user.avatar = f"/static/avatars/{filename}"
    await db.commit()
    return await _get_user_with_roles(db, user_id)
