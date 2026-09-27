"""Profile, sessions, and password API router."""
import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.v1.profile import service
from app.core.exceptions import AppException
from app.core.security import sha256_hex
from app.schemas.common import SuccessResponse
from app.schemas.profile import (
    ChangePasswordRequest,
    ProfileResponse,
    SessionResponse,
    UpdateProfileRequest,
)

router = APIRouter(prefix="/profile", tags=["profile"])

ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
EXT_MAP = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _current_refresh_hash(request: Request) -> str | None:
    """Extract raw refresh token from cookie and return its SHA-256 hash."""
    raw = request.cookies.get("refresh_token")
    if raw:
        return sha256_hex(raw)
    return None


# ── S-064: Profile ────────────────────────────────────────────────────────────

@router.get("/", response_model=SuccessResponse[ProfileResponse])
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(current_user["sub"])
    user = await service.get_profile(db, user_id)
    return SuccessResponse(data=ProfileResponse.model_validate(user), message="Berhasil")


@router.put("/", response_model=SuccessResponse[ProfileResponse])
async def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(current_user["sub"])
    user = await service.update_profile(db, user_id, name=body.name, request=request)
    return SuccessResponse(data=ProfileResponse.model_validate(user), message="Berhasil")


@router.post("/avatar", response_model=SuccessResponse[ProfileResponse])
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise AppException(
            code="PROFILE_AVATAR_INVALID_TYPE",
            message="Format file tidak didukung. Gunakan JPG, PNG, atau WebP",
            status_code=422,
        )

    file_data = await file.read()
    if len(file_data) > MAX_AVATAR_SIZE:
        raise AppException(
            code="PROFILE_AVATAR_TOO_LARGE",
            message="Ukuran file tidak boleh lebih dari 2MB",
            status_code=422,
        )

    ext = EXT_MAP[file.content_type]  # type: ignore[index]
    user_id = uuid.UUID(current_user["sub"])
    user = await service.upload_avatar(db, user_id, file_data, ext, request=request)
    return SuccessResponse(data=ProfileResponse.model_validate(user), message="Berhasil")


# ── S-065: Change Password ────────────────────────────────────────────────────

@router.put("/password", response_model=SuccessResponse[None])
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(current_user["sub"])
    current_token_hash = _current_refresh_hash(request)
    await service.change_password(
        db,
        user_id=user_id,
        current_password=body.current_password,
        new_password=body.new_password,
        confirm_password=body.confirm_password,
        current_token_hash=current_token_hash,
        request=request,
    )
    return SuccessResponse(data=None, message="Password berhasil diubah")


# ── S-066: Sessions ──────────────────────────────────────────────────────────

@router.get("/sessions", response_model=SuccessResponse[list[SessionResponse]])
async def list_sessions(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(current_user["sub"])
    current_token_hash = _current_refresh_hash(request)
    sessions = await service.list_sessions(db, user_id, current_token_hash)
    data = []
    for tok, is_current in sessions:
        resp = SessionResponse.model_validate(tok)
        resp.is_current = is_current
        data.append(resp)
    return SuccessResponse(data=data, message="Berhasil")


@router.delete("/sessions", response_model=SuccessResponse[None])
async def revoke_all_sessions(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(current_user["sub"])
    current_token_hash = _current_refresh_hash(request)
    await service.revoke_all_sessions(db, user_id, current_token_hash)
    return SuccessResponse(data=None, message="Semua sesi berhasil dicabut")


@router.delete("/sessions/{session_id}", response_model=SuccessResponse[None])
async def revoke_session(
    session_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = uuid.UUID(current_user["sub"])
    await service.revoke_session(db, user_id, session_id)
    return SuccessResponse(data=None, message="Sesi berhasil dicabut")
