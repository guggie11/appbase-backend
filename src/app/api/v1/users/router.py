"""Users API router."""
import contextlib
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.users import service
from app.core.exceptions import AppException
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.user import (
    AssignRolesRequest,
    CreateUserRequest,
    UpdateUserRequest,
    UpdateUserStatusRequest,
    UserWithRolesResponse,
)

router = APIRouter(prefix="/users", tags=["users"])

ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
EXT_MAP = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


@router.get("/", response_model=PaginatedResponse[UserWithRolesResponse])
async def list_users(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=100),
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    role_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("users.read")),
):
    users, total = await service.list_users(
        db, page=page, per_page=per_page, search=search, status=status, role_id=role_id
    )
    # Build response manually to include roles
    data = []
    for user in users:
        from app.schemas.role import RoleResponse
        roles = [RoleResponse.model_validate(ur.role) for ur in user.user_roles]
        user_resp = UserWithRolesResponse.model_validate(user)
        user_resp.roles = roles
        data.append(user_resp)

    return PaginatedResponse(data=data, total=total, page=page, per_page=per_page)


@router.post("/", response_model=SuccessResponse[UserWithRolesResponse], status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("users.create")),
):
    user = await service.create_user(db, name=body.name, email=body.email, role_ids=body.role_ids)
    # Send invitation email (fire and forget)
    with contextlib.suppress(Exception):
        from app.api.v1.auth.email import send_verification_email
        await send_verification_email(user.email, "invite")

    return _user_success(user, "User berhasil dibuat")


@router.put("/{user_id}", response_model=SuccessResponse[UserWithRolesResponse])
async def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("users.update")),
):
    user = await service.update_user(db, user_id, name=body.name, email=str(body.email) if body.email else None)
    return _user_success(user, "User berhasil diperbarui")


@router.delete("/{user_id}", response_model=SuccessResponse[None])
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("users.delete")),
):
    await service.delete_user(db, user_id)
    return SuccessResponse(data=None, message="User berhasil dihapus")


@router.patch("/{user_id}/status", response_model=SuccessResponse[UserWithRolesResponse])
async def update_status(
    user_id: uuid.UUID,
    body: UpdateUserStatusRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("users.update")),
):
    user = await service.update_status(db, user_id, body.status)
    return _user_success(user, "Status user berhasil diperbarui")


@router.post("/{user_id}/roles", response_model=SuccessResponse[UserWithRolesResponse])
async def assign_roles(
    user_id: uuid.UUID,
    body: AssignRolesRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("users.assign_role")),
):
    user = await service.assign_roles(db, user_id, body.role_ids)
    return _user_success(user, "Roles berhasil diperbarui")


@router.post("/{user_id}/avatar", response_model=SuccessResponse[UserWithRolesResponse])
async def upload_avatar(
    user_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("users.update")),
):
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise AppException(
            code="VALIDATION_ERROR",
            message="Format file tidak didukung. Gunakan jpg, png, atau webp.",
            status_code=400,
        )
    data = await file.read()
    if len(data) > MAX_AVATAR_SIZE:
        raise AppException(
            code="VALIDATION_ERROR",
            message="Ukuran file terlalu besar. Maksimal 2MB.",
            status_code=400,
        )

    ext = EXT_MAP[file.content_type]
    user = await service.upload_avatar(db, user_id, data, ext)
    return _user_success(user, "Avatar berhasil diperbarui")


def _user_success(user, message: str) -> SuccessResponse[UserWithRolesResponse]:
    from app.schemas.role import RoleResponse
    roles = [RoleResponse.model_validate(ur.role) for ur in user.user_roles]
    user_resp = UserWithRolesResponse.model_validate(user)
    user_resp.roles = roles
    return SuccessResponse(data=user_resp, message=message)
