"""Dashboard API business logic — S-059 stats + S-060 login activity."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import LoginAttempt
from app.models.user import User


async def get_stats(db: AsyncSession) -> dict:
    """S-059: Dashboard statistics."""
    # User counts per status
    user_status_result = await db.execute(
        select(User.status, func.count(User.id))
        .where(User.deleted_at.is_(None))
        .group_by(User.status)
    )
    status_counts: dict[str, int] = {}
    total_users = 0
    for status, count in user_status_result.fetchall():
        status_counts[status] = count
        total_users += count

    # Role count
    from app.models.rbac import Role

    role_count_result = await db.execute(select(func.count(Role.id)))
    role_count = role_count_result.scalar() or 0

    # Login attempts today
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    today_end = today_start + timedelta(days=1)

    login_today_result = await db.execute(
        select(LoginAttempt.success, func.count(LoginAttempt.id))
        .where(LoginAttempt.created_at >= today_start)
        .where(LoginAttempt.created_at < today_end)
        .group_by(LoginAttempt.success)
    )
    login_success = 0
    login_failed = 0
    for success, count in login_today_result.fetchall():
        if success:
            login_success = count
        else:
            login_failed = count

    return {
        "users": {
            "total": total_users,
            "active": status_counts.get("active", 0),
            "pending": status_counts.get("pending", 0),
            "inactive": status_counts.get("inactive", 0),
            "suspended": status_counts.get("suspended", 0),
        },
        "roles": {
            "total": role_count,
        },
        "today": {
            "login_success": login_success,
            "login_failed": login_failed,
        },
    }


async def get_login_activity(db: AsyncSession) -> list[dict]:
    """S-060: Login activity for last 30 days."""
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)

    result = await db.execute(
        select(
            func.date(LoginAttempt.created_at).label("date"),
            func.sum(cast(LoginAttempt.success, Integer)).label("success_count"),
            func.sum(cast(~LoginAttempt.success, Integer)).label("failed_count"),
        )
        .where(LoginAttempt.created_at >= since)
        .group_by(func.date(LoginAttempt.created_at))
        .order_by(func.date(LoginAttempt.created_at))
    )

    return [
        {
            "date": str(row.date),
            "success_count": int(row.success_count or 0),
            "failed_count": int(row.failed_count or 0),
        }
        for row in result.fetchall()
    ]
