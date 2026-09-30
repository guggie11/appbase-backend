"""Notifications API router."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.core.exceptions import AppException
from app.models.notification import Notification
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.notification import MarkReadResponse, NotificationResponse, UnreadCountResponse

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/unread-count", response_model=SuccessResponse[UnreadCountResponse])
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("notifications.read")),
):
    """Return count of unread notifications for current user."""
    user_id = uuid.UUID(current_user["sub"])
    result = await db.execute(
        select(func.count()).where(
            Notification.user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    count = result.scalar_one()
    return SuccessResponse(data=UnreadCountResponse(count=count), message="OK")


@router.get("/", response_model=PaginatedResponse[NotificationResponse])
async def list_notifications(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    unread: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("notifications.read")),
):
    """List notifications for the current logged-in user."""
    user_id = uuid.UUID(current_user["sub"])

    query = select(Notification).where(Notification.user_id == user_id)
    count_query = select(func.count()).where(Notification.user_id == user_id)

    if unread is not None:
        query = query.where(Notification.is_read == (not unread))
        count_query = count_query.where(Notification.is_read == (not unread))

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Notification.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    notifications = result.scalars().all()

    return PaginatedResponse(
        data=[NotificationResponse.model_validate(n) for n in notifications],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.patch("/read-all", response_model=SuccessResponse[MarkReadResponse])
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("notifications.read")),
):
    """Mark all notifications for current user as read."""
    user_id = uuid.UUID(current_user["sub"])
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    await db.commit()
    updated = result.rowcount
    return SuccessResponse(
        data=MarkReadResponse(updated=updated),
        message="Semua notifikasi telah dibaca",
    )


@router.patch("/{notification_id}/read", response_model=SuccessResponse[NotificationResponse])
async def mark_single_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("notifications.read")),
):
    """Mark a single notification as read (only if it belongs to current user)."""
    user_id = uuid.UUID(current_user["sub"])
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise AppException(
            code="NOT_FOUND",
            message="Notifikasi tidak ditemukan",
            status_code=404,
        )
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return SuccessResponse(
        data=NotificationResponse.model_validate(notif),
        message="Notifikasi telah dibaca",
    )
