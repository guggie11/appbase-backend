"""Dashboard router — S-059 stats + S-060 login activity."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.dashboard import service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", summary="Dashboard statistics (S-059)")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("dashboard.read")),
):
    data = await service.get_stats(db)
    return {"data": data, "message": "Berhasil"}


@router.get("/login-activity", summary="Login activity last 30 days (S-060)")
async def get_login_activity(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("dashboard.read")),
):
    data = await service.get_login_activity(db)
    return {"data": data, "message": "Berhasil"}
