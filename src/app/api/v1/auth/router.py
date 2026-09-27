"""Auth API router — all /api/v1/auth/* endpoints."""
import contextlib
import uuid

from fastapi import APIRouter, Cookie, Depends, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.v1.auth import email as email_service
from app.api.v1.auth import service
from app.core.audit import log_action
from app.schemas.auth import (
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


@router.get("/me", response_model=SuccessResponse[UserResponse])
async def get_me(
    payload: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(payload["sub"])
    user = await service.get_user_by_id(db, user_id)
    return SuccessResponse(data=UserResponse.model_validate(user), message="OK")
