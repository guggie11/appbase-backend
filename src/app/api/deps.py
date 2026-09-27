"""FastAPI dependencies."""
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
def require_permission(permission_slug: str):
    """Return a FastAPI dependency that checks if current user has a given permission."""

    async def checker(
        current_user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.core.exceptions import AppException
        from app.models.rbac import Permission, Role, RolePermission, UserRole

        user_id = current_user.get("sub")
        if not user_id:
            raise AppException(code="FORBIDDEN", message="Akses ditolak", status_code=403)

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

        # Check permission via role_permissions
        perm_result = await db.execute(
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .where(Permission.slug == permission_slug)
        )
        perm = perm_result.scalar_one_or_none()

        if not perm:
            raise AppException(code="FORBIDDEN", message="Akses ditolak", status_code=403)

        return current_user

    return checker
