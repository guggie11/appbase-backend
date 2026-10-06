"""FastAPI dependencies."""
import uuid as _uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Token tidak valid", "details": [], "request_id": None},
        ) from err

    # S-032: Check JWT blacklist
    jti = payload.get("jti")
    if jti:
        from app.core.redis import redis_client

        is_blacklisted = await redis_client.exists(f"blacklist:{jti}")
        if is_blacklisted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "AUTH_TOKEN_REVOKED", "message": "Token telah dicabut", "details": [], "request_id": None},
            )

    return payload


# S-050: Permission guard
#: Write actions that the module-wide ".manage" permission also covers.
_MANAGE_COVERS = ("create", "update", "delete")


def _accepted_slugs(permission_slug: str) -> list[str]:
    """Slugs that satisfy a required permission.

    `menu.create` is satisfied by `menu.create` or by the older `menu.manage`.
    Read and approve are deliberately excluded: `.manage` meant "may change
    things", never "may see things" or "may sign off".
    """
    accepted = [permission_slug]
    module, _, action = permission_slug.partition(".")
    if action in _MANAGE_COVERS:
        accepted.append(f"{module}.manage")
    return accepted


def require_permission(permission_slug: str):
    """Return a FastAPI dependency that checks if current user has a given permission."""

    async def checker(
        current_user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.core.exceptions import AppException
        from app.models.rbac import Permission, Role, RolePermission, UserRole

        user_id_str = current_user.get("sub")
        if not user_id_str:
            raise AppException(code="FORBIDDEN", message="Akses ditolak", status_code=403)

        try:
            user_id = _uuid.UUID(user_id_str)
        except (ValueError, AttributeError):
            raise AppException(code="FORBIDDEN", message="Akses ditolak", status_code=403) from None

        # Load user's roles
        result = await db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Role.is_active.is_(True))
        )
        roles = result.scalars().all()

        # Super-admin bypass
        for role in roles:
            if role.slug == "super-admin":
                return current_user

        # Check permission via role_permissions.
        #
        # A write action is satisfied either by its own slug (menu.create) or
        # by the module's legacy catch-all (menu.manage). Without the second
        # route, splitting .manage would revoke access from everyone already
        # holding it; without the first, the new per-action permissions would
        # be decorative.
        accepted = _accepted_slugs(permission_slug)

        perm_result = await db.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Permission.slug.in_(accepted))
        )
        perm = perm_result.scalars().first()

        if not perm:
            raise AppException(code="FORBIDDEN", message="Akses ditolak", status_code=403)

        return current_user

    return checker
