"""App settings API router."""
import os
import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.settings import service
from app.core.audit import log_action
from app.core.exceptions import AppException
from app.schemas.common import SuccessResponse
from app.schemas.setting import PublicSettingResponse, SettingResponse, UpdateSettingRequest

router = APIRouter(prefix="/settings", tags=["settings"])

_LOGO_DIR = "static/logos"
_LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
_FAVICON_MAX_BYTES = 512 * 1024  # 512 KB
_LOGO_ALLOWED = {"image/jpeg", "image/png", "image/svg+xml", "image/webp"}
_FAVICON_ALLOWED = {"image/x-icon", "image/vnd.microsoft.icon", "image/png"}
_LOGO_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/webp": "webp",
}
_FAVICON_EXTENSIONS = {
    "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
    "image/png": "png",
}


def _mask_if_secret(setting) -> SettingResponse:
    """Return SettingResponse; if is_secret=True, set value=None."""
    resp = SettingResponse.model_validate(setting)
    if setting.is_secret:
        resp.value = None
    return resp


async def _save_upload(
    file: UploadFile,
    allowed_content_types: set[str],
    ext_map: dict[str, str],
    max_bytes: int,
) -> str:
    """Validate and save an uploaded file; return the relative URL path."""
    content_type = file.content_type or ""
    if content_type not in allowed_content_types:
        raise AppException(
            code="INVALID_FILE_TYPE",
            message=f"Tipe file tidak didukung: {content_type}",
            status_code=422,
        )
    data = await file.read()
    if len(data) > max_bytes:
        raise AppException(
            code="FILE_TOO_LARGE",
            message=f"Ukuran file melebihi batas ({max_bytes // 1024} KB)",
            status_code=422,
        )
    ext = ext_map[content_type]
    filename = f"{uuid.uuid4()}.{ext}"
    os.makedirs(_LOGO_DIR, exist_ok=True)
    filepath = os.path.join(_LOGO_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(data)
    return f"/static/logos/{filename}"


# --- Public endpoint (NO AUTH) — MUST be before /{key} ---

@router.get("/public", response_model=SuccessResponse[list[PublicSettingResponse]])
async def list_public_settings(
    db: AsyncSession = Depends(get_db),
):
    """Return all settings where is_public=True. No authentication required."""
    from app.models.audit import AppSetting

    result = await db.execute(
        select(AppSetting).where(AppSetting.is_public == True).order_by(AppSetting.key)  # noqa: E712
    )
    settings = list(result.scalars().all())
    data = [PublicSettingResponse(key=s.key, value=s.value, type=s.type) for s in settings]
    return SuccessResponse(data=data, message="OK")


# --- Logo upload ---

@router.post("/logo", response_model=SuccessResponse[dict])
async def upload_logo(
    file: UploadFile = File(...),
    request: Request = None,  # type: ignore[assignment]
    current_user: dict = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Upload app logo (jpg/png/svg/webp, max 2 MB). Requires settings.manage permission."""
    url = await _save_upload(file, _LOGO_ALLOWED, _LOGO_EXTENSIONS, _LOGO_MAX_BYTES)

    user_id_str = current_user.get("sub")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    await service.update_setting(db, key="logo_url", value=url, updated_by=user_id)

    if request is not None:
        await log_action(
            db,
            user_id=user_id,
            action="update",
            module="settings",
            entity_id="logo_url",
            old_value=None,
            new_value={"value": url},
            request=request,
        )
        await db.commit()

    return SuccessResponse(data={"url": url}, message="Logo uploaded")


# --- Favicon upload ---

@router.post("/favicon", response_model=SuccessResponse[dict])
async def upload_favicon(
    file: UploadFile = File(...),
    request: Request = None,  # type: ignore[assignment]
    current_user: dict = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Upload app favicon (ico/png, max 512 KB). Requires settings.manage permission."""
    url = await _save_upload(file, _FAVICON_ALLOWED, _FAVICON_EXTENSIONS, _FAVICON_MAX_BYTES)

    user_id_str = current_user.get("sub")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    await service.update_setting(db, key="favicon_url", value=url, updated_by=user_id)

    if request is not None:
        await log_action(
            db,
            user_id=user_id,
            action="update",
            module="settings",
            entity_id="favicon_url",
            old_value=None,
            new_value={"value": url},
            request=request,
        )
        await db.commit()

    return SuccessResponse(data={"url": url}, message="Favicon uploaded")


# --- Protected list/update endpoints ---

@router.get("/", response_model=SuccessResponse[list[SettingResponse]])
async def list_settings(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("settings.read")),
):
    settings = await service.list_settings(db)
    data = [_mask_if_secret(s) for s in settings]
    return SuccessResponse(data=data, message="Berhasil")


@router.put("/{key}", response_model=SuccessResponse[SettingResponse])
async def update_setting(
    key: str,
    body: UpdateSettingRequest,
    request: Request,
    current_user: dict = Depends(require_permission("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    user_id_str = current_user.get("sub")
    user_id = uuid.UUID(user_id_str) if user_id_str else None

    # Capture old value before update
    from app.models.audit import AppSetting

    old_result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    old_setting = old_result.scalar_one_or_none()
    old_val = old_setting.value if old_setting else None

    setting = await service.update_setting(db, key=key, value=body.value, updated_by=user_id)

    await log_action(
        db,
        user_id=user_id,
        action="update",
        module="settings",
        entity_id=key,
        old_value={"value": old_val},
        new_value={"value": body.value},
        request=request,
    )
    await db.commit()

    return SuccessResponse(data=_mask_if_secret(setting), message="Berhasil")
