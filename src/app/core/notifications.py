"""Notification helper functions."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    message: str = "",
    type: str = "info",
    link: str | None = None,
) -> None:
    """Create and persist a notification for a user."""
    from app.models.notification import Notification

    notif = Notification(
        user_id=user_id,
        title=title,
        message=message,
        type=type,
        link=link,
    )
    db.add(notif)
    await db.commit()
