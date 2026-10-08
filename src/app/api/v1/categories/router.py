"""Categories API router.

Static routes are declared before "/{id}", or the catch-all swallows them.
"""
import contextlib
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.categories import service
from app.core.audit import log_action
from app.schemas.category import (
    CategoryGroupResponse,
    CategoryResponse,
    CreateCategoryGroupRequest,
    CreateCategoryRequest,
    DeprecateCategoryRequest,
    UpdateCategoryGroupRequest,
    UpdateCategoryRequest,
)
from app.schemas.common import SuccessResponse

router = APIRouter(prefix="/categories", tags=["categories"])


# ---------------------------------------------------------------------------
# What other features call
# ---------------------------------------------------------------------------


@router.get(
    "/by-group/{code}", response_model=SuccessResponse[list[CategoryResponse]]
)
async def list_by_group_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("category.read")),
):
    """Fetch a classification by group code.

    Returns active items only: a deprecated value must not reappear in a
    picker somewhere else in the application.
    """
    return SuccessResponse(data=await service.list_by_group_code(db, code))


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@router.get("/groups", response_model=SuccessResponse[list[CategoryGroupResponse]])
async def list_groups(
    is_active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("category.read")),
):
    return SuccessResponse(data=await service.list_groups(db, is_active=is_active))


@router.post(
    "/groups", response_model=SuccessResponse[CategoryGroupResponse], status_code=201
)
async def create_group(
    payload: CreateCategoryGroupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.create")),
):
    group = await service.create_group(db, payload)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="create",
            module="category-groups", entity_id=str(group.id), request=request,
        )
        await db.commit()
    return SuccessResponse(data=group)


@router.get(
    "/groups/{group_id}/tree", response_model=SuccessResponse[list[CategoryResponse]]
)
async def get_group_tree(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("category.read")),
):
    """Every item in the group, deprecated included — this is the management
    screen, where hiding them would make restoring impossible.
    """
    return SuccessResponse(data=await service.get_group_tree(db, group_id))


@router.get(
    "/groups/{group_id}", response_model=SuccessResponse[CategoryGroupResponse]
)
async def get_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("category.read")),
):
    return SuccessResponse(data=await service.get_group(db, group_id))


@router.patch(
    "/groups/{group_id}", response_model=SuccessResponse[CategoryGroupResponse]
)
async def update_group(
    group_id: uuid.UUID,
    payload: UpdateCategoryGroupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.update")),
):
    group = await service.update_group(db, group_id, payload)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="update",
            module="category-groups", entity_id=str(group_id), request=request,
        )
        await db.commit()
    return SuccessResponse(data=group)


@router.delete("/groups/{group_id}", response_model=SuccessResponse[dict])
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.delete")),
):
    await service.delete_group(db, group_id)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="delete",
            module="category-groups", entity_id=str(group_id), request=request,
        )
        await db.commit()
    return SuccessResponse(data={"deleted": True})


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@router.post("/", response_model=SuccessResponse[CategoryResponse], status_code=201)
async def create_category(
    payload: CreateCategoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.create")),
):
    row = await service.create_category(db, payload)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="create",
            module="categorys", entity_id=str(row.id), request=request,
        )
        await db.commit()
    return SuccessResponse(data=row)


@router.post(
    "/{category_id}/deprecate", response_model=SuccessResponse[CategoryResponse]
)
async def deprecate_category(
    category_id: uuid.UUID,
    payload: DeprecateCategoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.update")),
):
    row = await service.deprecate_category(db, category_id, payload.reason)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="deprecate",
            module="categorys", entity_id=str(category_id), request=request,
        )
        await db.commit()
    return SuccessResponse(data=row)


@router.post(
    "/{category_id}/restore", response_model=SuccessResponse[CategoryResponse]
)
async def restore_category(
    category_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.update")),
):
    row = await service.restore_category(db, category_id)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="restore",
            module="categorys", entity_id=str(category_id), request=request,
        )
        await db.commit()
    return SuccessResponse(data=row)


@router.get("/{category_id}", response_model=SuccessResponse[CategoryResponse])
async def get_category(
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("category.read")),
):
    return SuccessResponse(data=await service.get_category(db, category_id))


@router.patch("/{category_id}", response_model=SuccessResponse[CategoryResponse])
async def update_category(
    category_id: uuid.UUID,
    payload: UpdateCategoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.update")),
):
    row = await service.update_category(db, category_id, payload)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="update",
            module="categorys", entity_id=str(category_id), request=request,
        )
        await db.commit()
    return SuccessResponse(data=row)


@router.delete("/{category_id}", response_model=SuccessResponse[dict])
async def delete_category(
    category_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("category.delete")),
):
    await service.delete_category(db, category_id)
    with contextlib.suppress(Exception):
        await log_action(
            db, user_id=current_user.get("sub"), action="delete",
            module="categorys", entity_id=str(category_id), request=request,
        )
        await db.commit()
    return SuccessResponse(data={"deleted": True})
