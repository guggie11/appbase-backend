"""Audit log business logic service."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.user import User


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def list_audit_logs(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    module: str | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict], int]:
    """Return (list of row dicts with user_name, total)."""
    base_query = select(
        AuditLog,
        User.name.label("user_name"),
    ).outerjoin(User, User.id == AuditLog.user_id)

    count_query = select(func.count()).select_from(AuditLog)

    if user_id is not None:
        base_query = base_query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)

    if module:
        base_query = base_query.where(AuditLog.module == module)
        count_query = count_query.where(AuditLog.module == module)

    if action:
        base_query = base_query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    if date_from:
        base_query = base_query.where(AuditLog.created_at >= date_from)
        count_query = count_query.where(AuditLog.created_at >= date_from)

    if date_to:
        base_query = base_query.where(AuditLog.created_at <= date_to)
        count_query = count_query.where(AuditLog.created_at <= date_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    base_query = (
        base_query
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(base_query)
    rows = result.all()

    items = []
    for row in rows:
        log: AuditLog = row[0]
        user_name: str | None = row[1]
        items.append({
            "id": log.id,
            "user_id": log.user_id,
            "user_name": user_name,
            "action": log.action,
            "module": log.module,
            "entity_id": log.entity_id,
            "ip_address": log.ip_address,
            "request_id": log.request_id,
            "created_at": log.created_at,
        })

    return items, total
