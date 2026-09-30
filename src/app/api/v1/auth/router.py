"""Auth API router — all /api/v1/auth/* endpoints."""
import contextlib
import uuid

from fastapi import APIRouter, Cookie, Depends, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.v1.auth import email as email_service
from app.api.v1.auth import oauth as oauth_service
from app.api.v1.auth import service
from app.core.audit import log_action
from app.core.redis import redis_client
from app.models.token import RefreshToken
from app.schemas.auth import (
    AcceptInvitationRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserBriefResponse,
    UserResponse,
)
from app.schemas.common import SuccessResponse

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=SuccessResponse[dict])
@limiter.limit("5/hour")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    user, raw_token = await service.register_user(db, body.name, body.email, body.password)
    # Send verification email (fire-and-forget — don't fail if SMTP unavailable)
    with contextlib.suppress(Exception):
        await email_service.send_verification_email(user.email, raw_token)
    return SuccessResponse(
        data={"id": str(user.id), "email": user.email, "name": user.name, "status": user.status},
        message="Registrasi berhasil, cek email untuk verifikasi",
    )


@router.post("/login", response_model=SuccessResponse[TokenResponse])
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    access_token, _jti, raw_refresh, user = await service.login_user(
        db, body.email, body.password, ip_address=ip, user_agent=ua
    )

    # Audit: login success
    with contextlib.suppress(Exception):
        await log_action(db, user_id=user.id, action="login", module="auth", entity_id=str(user.id), request=request)
        await db.commit()

    # Set cookies
    csrf_token = str(uuid.uuid4())
    response.set_cookie(
        "refresh_token",
        raw_refresh,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    response.set_cookie(
        "csrf_token",
        csrf_token,
        httponly=False,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )

    return SuccessResponse(
        data=TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=UserBriefResponse.model_validate(user),
        ),
        message="Login berhasil",
    )


@router.post("/logout", response_model=SuccessResponse[None])
async def logout(
    request: Request,
    response: Response,
    payload: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    jti = payload.get("jti")
    token_exp = payload.get("exp", 0)
    raw_refresh = request.cookies.get("refresh_token")

    if jti:
        await service.logout_user(db, jti, token_exp, raw_refresh)

    response.delete_cookie("refresh_token")
    response.delete_cookie("csrf_token")
    return SuccessResponse(data=None, message="Logout berhasil")


@router.post("/logout-all", response_model=SuccessResponse[dict])
async def logout_all(
    request: Request,
    response: Response,
    payload: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all active sessions for the current user."""
    user_id = uuid.UUID(payload["sub"])
    jti = payload.get("jti")
    token_exp = payload.get("exp", 0)

    # Blacklist current access token
    if jti:
        now_ts = int(service._now().timestamp())
        ttl = max(token_exp - now_ts, 1)
        await redis_client.setex(f"blacklist:{jti}", ttl, "1")

    # Count active refresh tokens before revoking
    count_result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    sessions_revoked = len(count_result.scalars().all())

    # Bulk-revoke all active refresh tokens
    if sessions_revoked > 0:
        now = service._now()
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await db.commit()

    response.delete_cookie("refresh_token")
    response.delete_cookie("csrf_token")
    return SuccessResponse(
        data={"sessions_revoked": sessions_revoked},
        message="Semua sesi berhasil diakhiri",
    )


@router.post("/refresh", response_model=SuccessResponse[dict])
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None),
):
    from app.core.exceptions import AppException

    if not refresh_token:
        raise AppException("AUTH_TOKEN_INVALID", "Refresh token tidak ditemukan", 401)

    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    new_access, _new_jti, new_raw = await service.refresh_tokens(
        db, refresh_token, ip_address=ip, user_agent=ua
    )

    response.set_cookie(
        "refresh_token",
        new_raw,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )

    return SuccessResponse(data={"access_token": new_access}, message="Token diperbarui")


@router.post("/forgot-password", response_model=SuccessResponse[None])
@limiter.limit("5/hour")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    raw_token = await service.forgot_password(db, body.email)
    if raw_token:
        with contextlib.suppress(Exception):
            await email_service.send_reset_email(body.email, raw_token)
    return SuccessResponse(data=None, message="Jika email terdaftar, link reset akan dikirim")


@router.post("/reset-password", response_model=SuccessResponse[None])
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    await service.reset_password(db, body.token, body.password)
    return SuccessResponse(data=None, message="Password berhasil diubah")


@router.get("/verify-email", response_model=SuccessResponse[None])
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    await service.verify_email(db, token)
    return SuccessResponse(data=None, message="Email berhasil diverifikasi")


@router.post("/resend-verification", response_model=SuccessResponse[None])
async def resend_verification(
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    raw_token = await service.resend_verification(db, body.email)
    if raw_token:
        with contextlib.suppress(Exception):
            await email_service.send_verification_email(body.email, raw_token)
    return SuccessResponse(
        data=None,
        message="Jika email terdaftar dan belum diverifikasi, email akan dikirim",
    )


@router.post("/accept-invitation", response_model=SuccessResponse[None])
async def accept_invitation(
    body: AcceptInvitationRequest,
    db: AsyncSession = Depends(get_db),
):
    await service.accept_invitation(db, body.token, body.password)
    return SuccessResponse(data=None, message="Password berhasil dibuat, silakan login")


@router.get("/me", response_model=SuccessResponse[UserResponse])
async def get_me(
    payload: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(payload["sub"])
    user = await service.get_user_by_id(db, user_id)
    return SuccessResponse(data=UserResponse.model_validate(user), message="OK")


# ---------------------------------------------------------------------------
# OAuth / SSO endpoints (C2)
# ---------------------------------------------------------------------------

_SUPPORTED_PROVIDERS = {"google", "microsoft", "tgsso"}


@router.get("/oauth/{provider}")
async def oauth_redirect(
    provider: str,
    db: AsyncSession = Depends(get_db),
):
    """Redirect browser to the OAuth provider's authorization page."""
    from fastapi.responses import RedirectResponse

    from app.core.config import settings
    from app.core.exceptions import AppException

    if provider not in _SUPPORTED_PROVIDERS:
        raise AppException(
            "OAUTH_UNSUPPORTED_PROVIDER",
            f"Provider '{provider}' is not supported. Use: {', '.join(sorted(_SUPPORTED_PROVIDERS))}",
            400,
        )
    if not oauth_service.is_provider_configured(provider, settings):
        raise AppException(
            "OAUTH_PROVIDER_NOT_CONFIGURED",
            f"Provider '{provider}' is not configured. Set the required environment variables.",
            400,
        )
    auth_url = await oauth_service.get_oauth_redirect_url(provider, settings)
    return RedirectResponse(url=auth_url)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Handle the callback from an OAuth provider."""
    from fastapi.responses import RedirectResponse

    from app.core.config import settings
    from app.core.exceptions import AppException

    error_redirect_base = settings.OAUTH_ERROR_REDIRECT

    if provider not in _SUPPORTED_PROVIDERS:
        return RedirectResponse(url=f"{error_redirect_base}?error=unsupported_provider")

    if error:
        return RedirectResponse(url=f"{error_redirect_base}?error={error}")

    if not code or not state:
        return RedirectResponse(url=f"{error_redirect_base}?error=missing_code_or_state")

    try:
        access_token, raw_refresh = await oauth_service.handle_oauth_callback(
            provider, code, state, db, settings
        )
    except AppException as exc:
        import urllib.parse
        err_msg = urllib.parse.quote(exc.message or exc.code)
        return RedirectResponse(url=f"{error_redirect_base}?error={err_msg}")
    except Exception:
        return RedirectResponse(url=f"{error_redirect_base}?error=internal_error")

    success_url = (
        f"{settings.OAUTH_SUCCESS_REDIRECT}"
        f"?access_token={access_token}"
        f"&token_type=bearer"
    )
    response = RedirectResponse(url=success_url)
    response.set_cookie(
        "refresh_token",
        raw_refresh,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    csrf_token = str(uuid.uuid4())
    response.set_cookie(
        "csrf_token",
        csrf_token,
        httponly=False,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response
