"""App settings API router."""
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.settings import service
from app.core.audit import log_action
from app.schemas.common import SuccessResponse
from app.schemas.setting import SettingResponse, UpdateSettingRequest

router = APIRouter(prefix="/settings", tags=["settings"])


def _mask_if_secret(setting) -> SettingResponse:
    """Return SettingResponse; if is_secret=True, set value=None."""
    resp = SettingResponse.model_validate(setting)
    if setting.is_secret:
        resp.value = None
    return resp


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
    from sqlalchemy import select

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
