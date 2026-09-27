"""Audit log helper: log_action()."""
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

# Fields that must never appear in audit logs
_SENSITIVE_FIELDS = {"password", "password_hash", "token", "secret"}


def _sanitize(value: Any) -> Any:
    """Recursively remove sensitive keys from a dict."""
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items() if k not in _SENSITIVE_FIELDS}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def log_action(
    db: AsyncSession,
    user_id: uuid.UUID | str | None,
    action: str,
    module: str,
    entity_id: str | None = None,
    old_value: Any | None = None,
    new_value: Any | None = None,
    request: Request | None = None,
) -> None:
    """Persist an audit log entry.

    Sensitive fields (password, password_hash, token, secret) are stripped
    from old_value / new_value before storing.
    """
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None

    if request is not None:
        ip_address = request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else None
        )
        user_agent = request.headers.get("user-agent")
        request_id = getattr(request.state, "request_id", None)
        if request_id is not None:
            request_id = str(request_id)

    if isinstance(user_id, str):
        try:
            user_id = uuid.UUID(user_id)
        except ValueError:
            user_id = None

    entry = AuditLog(
        id=uuid.uuid4(),
        user_id=user_id,
        action=action,
        module=module,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_value=_sanitize(old_value) if old_value is not None else None,
        new_value=_sanitize(new_value) if new_value is not None else None,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        created_at=_now(),
    )
    db.add(entry)
    # We intentionally do NOT commit here — the caller is responsible for commit.
    # This lets log_action be part of an existing transaction.
    await db.flush()
