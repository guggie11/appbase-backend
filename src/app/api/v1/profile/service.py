"""Profile, password, sessions business logic service."""
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.exceptions import AppException
from app.core.security import hash_password, verify_password
from app.models.token import RefreshToken
from app.models.user import PasswordHistory, User

_PASSWORD_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^a-zA-Z\d]).{8,}$"
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(code="PROFILE_NOT_FOUND", message="User tidak ditemukan", status_code=404)
    return user


# ── S-064: Get / Update Profile ──────────────────────────────────────────────

async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> User:
    return await _get_user(db, user_id)


async def update_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    request: Request | None = None,
) -> User:
    user = await _get_user(db, user_id)
    old_name = user.name
    user.name = name
    await log_action(
        db,
        user_id=user_id,
        action="update",
        module="profile",
        entity_id=str(user_id),
        old_value={"name": old_name},
        new_value={"name": name},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return user


async def upload_avatar(
    db: AsyncSession,
    user_id: uuid.UUID,
    file_data: bytes,
    ext: str,
    request: Request | None = None,
) -> User:
    user = await _get_user(db, user_id)

    avatar_dir = Path("static/avatars")
    avatar_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{user_id}.{ext}"
    filepath = avatar_dir / filename
    with open(filepath, "wb") as f:
        f.write(file_data)

    old_avatar = user.avatar
    user.avatar = f"/static/avatars/{filename}"
    await log_action(
        db,
        user_id=user_id,
        action="update",
        module="profile",
        entity_id=str(user_id),
        old_value={"avatar": old_avatar},
        new_value={"avatar": user.avatar},
        request=request,
    )
    await db.commit()
    await db.refresh(user)
    return user


# ── S-065: Change Password ────────────────────────────────────────────────────

async def change_password(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_password: str,
    new_password: str,
    confirm_password: str,
    current_token_hash: str | None = None,
    request: Request | None = None,
) -> None:
    user = await _get_user(db, user_id)

    # Verify current password
    if not user.password_hash or not verify_password(current_password, user.password_hash):
        raise AppException(
            code="PROFILE_WRONG_PASSWORD",
            message="Password saat ini tidak valid",
            status_code=400,
        )

    # Validate new password policy
    if not _PASSWORD_RE.match(new_password):
        raise AppException(
            code="VALIDATION_ERROR",
            message="Password harus minimal 8 karakter dan mengandung huruf besar, kecil, angka, dan simbol",
            status_code=422,
        )

    if new_password != confirm_password:
        raise AppException(
            code="VALIDATION_ERROR",
            message="Konfirmasi password tidak cocok",
            status_code=422,
        )

    # Check against password history (last 5)
    history_result = await db.execute(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(5)
    )
    histories = history_result.scalars().all()
    for hist in histories:
        if verify_password(new_password, hist.password_hash):
            raise AppException(
                code="PROFILE_SAME_PASSWORD",
                message="Password baru tidak boleh sama dengan 5 password sebelumnya",
                status_code=400,
            )

    # Also check current password
    if verify_password(new_password, user.password_hash):
        raise AppException(
            code="PROFILE_SAME_PASSWORD",
            message="Password baru tidak boleh sama dengan password saat ini",
            status_code=400,
        )

    # Save current hash to history
    db.add(PasswordHistory(id=uuid.uuid4(), user_id=user_id, password_hash=user.password_hash))

    # Update password
    user.password_hash = hash_password(new_password)

    # Trim history to 5
    all_hist_result = await db.execute(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user_id)
        .order_by(PasswordHistory.created_at.desc())
    )
    all_hist = all_hist_result.scalars().all()
    if len(all_hist) > 5:
        for old in all_hist[5:]:
            await db.delete(old)

    # Revoke all refresh tokens EXCEPT current
    if current_token_hash:
        await db.execute(
            update(RefreshToken)
            .where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.token_hash != current_token_hash,
                )
            )
            .values(revoked_at=_now())
        )
    else:
        await db.execute(
            update(RefreshToken)
            .where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
            .values(revoked_at=_now())
        )

    await log_action(
        db,
        user_id=user_id,
        action="change_password",
        module="profile",
        entity_id=str(user_id),
        request=request,
    )
    await db.commit()


# ── S-066: Sessions ──────────────────────────────────────────────────────────

async def list_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_token_hash: str | None = None,
) -> list[tuple[RefreshToken, bool]]:
    result = await db.execute(
        select(RefreshToken)
        .where(
            and_(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > _now(),
            )
        )
        .order_by(RefreshToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return [
        (tok, tok.token_hash == current_token_hash)
        for tok in tokens
    ]


async def revoke_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    result = await db.execute(
        select(RefreshToken).where(
            and_(
                RefreshToken.id == session_id,
                RefreshToken.user_id == user_id,
            )
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise AppException(
            code="SESSIONS_NOT_FOUND",
            message="Sesi tidak ditemukan",
            status_code=404,
        )
    token.revoked_at = _now()
    await db.commit()


async def revoke_all_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_token_hash: str | None = None,
) -> None:
    if current_token_hash:
        await db.execute(
            update(RefreshToken)
            .where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.token_hash != current_token_hash,
                )
            )
            .values(revoked_at=_now())
        )
    else:
        await db.execute(
            update(RefreshToken)
            .where(
                and_(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
            .values(revoked_at=_now())
        )
    await db.commit()
