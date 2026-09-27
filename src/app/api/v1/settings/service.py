"""App settings business logic service."""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.audit import AppSetting


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def list_settings(db: AsyncSession) -> list[AppSetting]:
    result = await db.execute(select(AppSetting).order_by(AppSetting.key))
    return list(result.scalars().all())


async def update_setting(
    db: AsyncSession,
    key: str,
    value: str | None,
    updated_by=None,
) -> AppSetting:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise AppException(
            code="SETTINGS_NOT_FOUND",
            message=f"Setting '{key}' tidak ditemukan",
            status_code=404,
        )
    setting.value = value
    setting.updated_at = _now()
    if updated_by is not None:
        setting.updated_by = updated_by
    await db.commit()
    await db.refresh(setting)
    return setting
