"""Auth business logic service."""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import exceptions as exc
from app.core.security import (
    create_access_token,
    create_raw_refresh_token,
    hash_password,
    sha256_hex,
    verify_password,
)
from app.models.token import LoginAttempt, RefreshToken
from app.models.user import EmailVerification, PasswordHistory, PasswordReset, User


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def register_user(db: AsyncSession, name: str, email: str, password: str) -> tuple[User, str]:
    # Check if email exists
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing:
        raise exc.auth_email_already_exists()

    pw_hash = hash_password(password)
    user = User(
        id=uuid.uuid4(),
        name=name,
        email=email,
        password_hash=pw_hash,
        status="pending",
        is_verified=False,
    )
    db.add(user)
    await db.flush()  # get id

    # Create email verification token
    raw_token, token_hash = _generate_token_pair()
    verification = EmailVerification(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=_now() + timedelta(hours=24),
    )
    db.add(verification)
    await db.commit()
    await db.refresh(user)
    return user, raw_token


def _generate_token_pair() -> tuple[str, str]:
    """Returns (raw_hex_token, sha256_hash)."""
    import os
    raw = os.urandom(32).hex()
    return raw, sha256_hex(raw)


async def login_user(
    db: AsyncSession,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str, str, User]:
    """Returns (access_token, jti, raw_refresh_token, user)."""
    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()

    # Check account locked
    if user and user.locked_until and user.locked_until > _now():
        raise exc.auth_account_locked()

    # Verify password
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        if user:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= 5:
                user.locked_until = _now() + timedelta(minutes=15)
            db.add(LoginAttempt(
                id=uuid.uuid4(), email=email, ip_address=ip_address, success=False
            ))
            await db.commit()
        raise exc.auth_invalid_credentials()

    # Check email verified
    if not user.is_verified:
        db.add(LoginAttempt(id=uuid.uuid4(), email=email, ip_address=ip_address, success=True))
        await db.commit()
        raise exc.auth_email_not_verified()

    # Success
    user.failed_login_count = 0
    user.last_login_at = _now()
    db.add(LoginAttempt(id=uuid.uuid4(), email=email, ip_address=ip_address, success=True))

    access_token, jti = create_access_token(str(user.id))
    raw_refresh, refresh_hash = create_raw_refresh_token()

    refresh_token = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=_now() + timedelta(days=7),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(refresh_token)
    await db.commit()
    await db.refresh(user)
    return access_token, jti, raw_refresh, user


async def logout_user(
    db: AsyncSession,
    jti: str,
    token_exp: int,
    raw_refresh_token: str | None,
) -> None:
    from app.core.redis import redis_client

    now_ts = int(_now().timestamp())
    ttl = max(token_exp - now_ts, 1)
    await redis_client.setex(f"blacklist:{jti}", ttl, "1")

    if raw_refresh_token:
        token_hash = sha256_hex(raw_refresh_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        rt = result.scalar_one_or_none()
        if rt and rt.revoked_at is None:
            rt.revoked_at = _now()
            await db.commit()


async def refresh_tokens(
    db: AsyncSession,
    raw_refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str, str]:
    """Returns (new_access_token, new_jti, new_raw_refresh_token)."""
    token_hash = sha256_hex(raw_refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()

    if not rt:
        raise exc.auth_token_invalid()

    if rt.revoked_at is not None:
        # Token reuse detected — revoke all refresh tokens for this user
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == rt.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await db.commit()
        raise exc.auth_token_revoked()

    if rt.expires_at < _now():
        raise exc.auth_token_expired()

    # Rotate token
    rt.revoked_at = _now()
    new_access_token, new_jti = create_access_token(str(rt.user_id))
    new_raw, new_hash = create_raw_refresh_token()
    new_rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=rt.user_id,
        token_hash=new_hash,
        expires_at=_now() + timedelta(days=7),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(new_rt)
    await db.commit()
    return new_access_token, new_jti, new_raw


async def forgot_password(db: AsyncSession, email: str) -> str | None:
    """Returns raw_token if user exists (for email sending), else None."""
    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user:
        return None

    raw_token, token_hash = _generate_token_pair()
    reset = PasswordReset(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=_now() + timedelta(hours=1),
    )
    db.add(reset)
    await db.commit()
    return raw_token


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    token_hash = sha256_hex(token)
    result = await db.execute(
        select(PasswordReset).where(
            PasswordReset.token_hash == token_hash,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > _now(),
        )
    )
    pr = result.scalar_one_or_none()
    if not pr:
        raise exc.auth_invalid_reset_token()

    # Get user
    user_result = await db.execute(select(User).where(User.id == pr.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise exc.auth_user_not_found()

    # Check last 5 password histories
    history_result = await db.execute(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
        .limit(5)
    )
    histories = history_result.scalars().all()
    for hist in histories:
        if verify_password(new_password, hist.password_hash):
            raise exc.auth_same_password()

    # Also check current password
    if user.password_hash and verify_password(new_password, user.password_hash):
        raise exc.auth_same_password()

    # Save old hash to history
    if user.password_hash:
        db.add(PasswordHistory(id=uuid.uuid4(), user_id=user.id, password_hash=user.password_hash))

    # Update password
    user.password_hash = hash_password(new_password)
    pr.used_at = _now()

    # Revoke all refresh tokens
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )

    # Trim password history to 5
    all_history_result = await db.execute(
        select(PasswordHistory)
        .where(PasswordHistory.user_id == user.id)
        .order_by(PasswordHistory.created_at.desc())
    )
    all_hist = all_history_result.scalars().all()
    if len(all_hist) > 5:
        for old in all_hist[5:]:
            await db.delete(old)

    await db.commit()


async def verify_email(db: AsyncSession, token: str) -> None:
    token_hash = sha256_hex(token)
    result = await db.execute(
        select(EmailVerification).where(
            EmailVerification.token_hash == token_hash,
            EmailVerification.used_at.is_(None),
            EmailVerification.expires_at > _now(),
        )
    )
    ev = result.scalar_one_or_none()
    if not ev:
        raise exc.auth_invalid_verify_token()

    user_result = await db.execute(select(User).where(User.id == ev.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise exc.auth_user_not_found()

    user.is_verified = True
    user.status = "active"
    ev.used_at = _now()
    await db.commit()


async def resend_verification(db: AsyncSession, email: str) -> str | None:
    """Returns raw_token if user found and unverified, else None."""
    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user or user.is_verified:
        return None

    # Invalidate old tokens
    await db.execute(
        update(EmailVerification)
        .where(EmailVerification.user_id == user.id, EmailVerification.used_at.is_(None))
        .values(used_at=_now())
    )

    raw_token, token_hash = _generate_token_pair()
    db.add(EmailVerification(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        expires_at=_now() + timedelta(hours=24),
    ))
    await db.commit()
    return raw_token


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if not user:
        raise exc.auth_user_not_found()
    return user


async def accept_invitation(db: AsyncSession, token: str, new_password: str) -> None:
    token_hash = sha256_hex(token)
    from app.models.user import UserInvitation
    result = await db.execute(
        select(UserInvitation).where(
            UserInvitation.token_hash == token_hash,
            UserInvitation.used_at.is_(None),
        )
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise exc.auth_invalid_invitation_token()

    if invitation.expires_at < _now():
        raise exc.auth_invitation_expired()

    # Get user
    user_result = await db.execute(select(User).where(User.id == invitation.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise exc.auth_user_not_found()

    # Update user: set password, activate, verify
    user.password_hash = hash_password(new_password)
    user.status = "active"
    user.is_verified = True

    # Mark invitation as used
    invitation.used_at = _now()

    await db.commit()
