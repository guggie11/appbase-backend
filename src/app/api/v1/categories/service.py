"""Category business logic.

The interesting parts are the refusals: an immutable code, a parent that must
share the group, a cycle, a deprecation without a reason. Each exists because
the alternative corrupts reference data quietly.
"""
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.category import Category, CategoryGroup
from app.schemas.category import (
    CreateCategoryGroupRequest,
    CreateCategoryRequest,
    UpdateCategoryGroupRequest,
    UpdateCategoryRequest,
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
    return slug.strip("-")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


async def list_groups(
    db: AsyncSession, is_active: bool | None = None
) -> list[CategoryGroup]:
    query = select(CategoryGroup).order_by(CategoryGroup.name)
    if is_active is not None:
        query = query.where(CategoryGroup.is_active == is_active)
    groups = list((await db.execute(query)).scalars().all())
    await _attach_counts(db, groups)
    return groups


async def _attach_counts(db: AsyncSession, groups: list[CategoryGroup]) -> None:
    """One aggregate query; a default of 0 would be a number that lies."""
    if not groups:
        return
    rows = (
        await db.execute(
            select(Category.group_id, func.count(Category.id))
            .where(Category.group_id.in_([g.id for g in groups]))
            .group_by(Category.group_id)
        )
    ).all()
    counts = dict(rows)
    for group in groups:
        group.category_count = counts.get(group.id, 0)


async def get_group(db: AsyncSession, group_id: uuid.UUID) -> CategoryGroup:
    group = (
        await db.execute(select(CategoryGroup).where(CategoryGroup.id == group_id))
    ).scalar_one_or_none()
    if group is None:
        raise AppException(
            code="NOT_FOUND", message="Category group tidak ditemukan", status_code=404
        )
    await _attach_counts(db, [group])
    return group


async def get_group_by_code(db: AsyncSession, code: str) -> CategoryGroup:
    group = (
        await db.execute(select(CategoryGroup).where(CategoryGroup.code == code))
    ).scalar_one_or_none()
    if group is None:
        raise AppException(
            code="NOT_FOUND",
            message=f"Category group '{code}' tidak ditemukan",
            status_code=404,
        )
    return group


async def create_group(
    db: AsyncSession, payload: CreateCategoryGroupRequest
) -> CategoryGroup:
    code = _slugify(payload.code or payload.name)
    if not code:
        raise AppException(
            code="VALIDATION_ERROR",
            message="Code tidak boleh kosong",
            status_code=400,
        )

    existing = (
        await db.execute(select(CategoryGroup).where(CategoryGroup.code == code))
    ).scalar_one_or_none()
    if existing is not None:
        raise AppException(
            code="CONFLICT",
            message=f"Code '{code}' sudah dipakai group lain",
            status_code=409,
        )

    group = CategoryGroup(
        id=uuid.uuid4(),
        code=code,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        color=payload.color,
        is_system=False,
        is_active=True,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    group.category_count = 0
    return group


async def update_group(
    db: AsyncSession, group_id: uuid.UUID, payload: UpdateCategoryGroupRequest
) -> CategoryGroup:
    """`code` is deliberately absent: other tables reference it."""
    group = await get_group(db, group_id)

    if payload.name is not None:
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    if payload.icon is not None:
        group.icon = payload.icon
    if payload.color is not None:
        group.color = payload.color
    if payload.is_active is not None:
        group.is_active = payload.is_active

    await db.commit()
    await db.refresh(group)
    await _attach_counts(db, [group])
    return group


async def delete_group(db: AsyncSession, group_id: uuid.UUID) -> None:
    group = await get_group(db, group_id)

    if group.is_system:
        raise AppException(
            code="FORBIDDEN",
            message="Group bawaan sistem tidak bisa dihapus",
            status_code=403,
        )

    count = (
        await db.execute(
            select(func.count(Category.id)).where(Category.group_id == group_id)
        )
    ).scalar_one()
    if count:
        raise AppException(
            code="CONFLICT",
            message=(
                f"Group masih memiliki {count} kategori. "
                "Hapus atau pindahkan kategorinya terlebih dahulu."
            ),
            status_code=409,
        )

    await db.delete(group)
    await db.commit()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


async def get_category(db: AsyncSession, category_id: uuid.UUID) -> Category:
    row = (
        await db.execute(select(Category).where(Category.id == category_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppException(
            code="NOT_FOUND", message="Kategori tidak ditemukan", status_code=404
        )
    return row


async def _assert_parent_is_valid(
    db: AsyncSession,
    group_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    moving_id: uuid.UUID | None = None,
) -> None:
    """A parent must share the group, and must not create a cycle."""
    if parent_id is None:
        return

    if moving_id is not None and parent_id == moving_id:
        raise AppException(
            code="VALIDATION_ERROR",
            message="Kategori tidak bisa menjadi induk dirinya sendiri",
            status_code=400,
        )

    parent = (
        await db.execute(select(Category).where(Category.id == parent_id))
    ).scalar_one_or_none()
    if parent is None:
        raise AppException(
            code="NOT_FOUND", message="Induk tidak ditemukan", status_code=404
        )
    if parent.group_id != group_id:
        raise AppException(
            code="VALIDATION_ERROR",
            message="Induk harus berada di group yang sama",
            status_code=400,
        )

    if moving_id is None:
        return

    # Walk up from the proposed parent: meeting the node being moved means
    # the move would close a loop and make the tree infinite.
    seen: set[uuid.UUID] = set()
    cursor: uuid.UUID | None = parent.parent_id
    while cursor is not None:
        if cursor == moving_id:
            raise AppException(
                code="VALIDATION_ERROR",
                message="Perpindahan ini membuat hierarki melingkar",
                status_code=400,
            )
        if cursor in seen:
            break
        seen.add(cursor)
        ancestor = (
            await db.execute(select(Category).where(Category.id == cursor))
        ).scalar_one_or_none()
        cursor = ancestor.parent_id if ancestor else None


async def create_category(
    db: AsyncSession, payload: CreateCategoryRequest
) -> Category:
    await get_group(db, payload.group_id)

    code = _slugify(payload.code or payload.name)
    if not code:
        raise AppException(
            code="VALIDATION_ERROR", message="Code tidak boleh kosong", status_code=400
        )

    clash = (
        await db.execute(
            select(Category).where(
                Category.group_id == payload.group_id, Category.code == code
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise AppException(
            code="CONFLICT",
            message=f"Code '{code}' sudah dipakai di group ini",
            status_code=409,
        )

    await _assert_parent_is_valid(db, payload.group_id, payload.parent_id)

    row = Category(
        id=uuid.uuid4(),
        group_id=payload.group_id,
        parent_id=payload.parent_id,
        code=code,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        color=payload.color,
        order_index=payload.order_index,
        is_system=False,
        status="active",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_category(
    db: AsyncSession, category_id: uuid.UUID, payload: UpdateCategoryRequest
) -> Category:
    """`code` is deliberately absent: it is the reference key."""
    row = await get_category(db, category_id)

    if payload.parent_id is not None:
        await _assert_parent_is_valid(
            db, row.group_id, payload.parent_id, moving_id=row.id
        )
        row.parent_id = payload.parent_id

    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    if payload.icon is not None:
        row.icon = payload.icon
    if payload.color is not None:
        row.color = payload.color
    if payload.order_index is not None:
        row.order_index = payload.order_index

    await db.commit()
    await db.refresh(row)
    return row


async def delete_category(db: AsyncSession, category_id: uuid.UUID) -> None:
    """Deleting is the exception; deprecating is the normal path.

    Rows referenced by other tables are refused by the database itself
    (ON DELETE RESTRICT), which is why no application-level scan is needed.
    """
    row = await get_category(db, category_id)

    if row.is_system:
        raise AppException(
            code="FORBIDDEN",
            message="Kategori bawaan sistem tidak bisa dihapus, hanya di-deprecate",
            status_code=403,
        )

    # Captured now: after a failed delete the instance is expired, and
    # touching it would trigger a lazy load outside the async context.
    label = row.name

    children = (
        await db.execute(
            select(func.count(Category.id)).where(Category.parent_id == category_id)
        )
    ).scalar_one()
    if children:
        raise AppException(
            code="CONFLICT",
            message=f"Kategori ini memiliki {children} turunan",
            status_code=409,
        )

    try:
        await db.delete(row)
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        # Another table still points at this row. The database caught it;
        # turn that into an answer rather than a 500.
        await db.rollback()
        # The rollback expired every instance; reload this one explicitly so
        # the caller is not handed an object that refreshes itself lazily.
        await db.refresh(row)
        raise AppException(
            code="CONFLICT",
            message=(
                f"Kategori '{label}' masih dirujuk data lain sehingga tidak "
                "bisa dihapus. Gunakan deprecate agar rujukan yang ada "
                "tetap utuh."
            ),
            status_code=409,
        ) from exc


async def deprecate_category(
    db: AsyncSession, category_id: uuid.UUID, reason: str
) -> Category:
    row = await get_category(db, category_id)

    if not (reason or "").strip():
        raise AppException(
            code="VALIDATION_ERROR",
            message="Alasan deprecasi wajib diisi",
            status_code=400,
        )

    row.status = "deprecated"
    row.deprecated_reason = reason.strip()
    await db.commit()
    await db.refresh(row)
    return row


async def restore_category(db: AsyncSession, category_id: uuid.UUID) -> Category:
    row = await get_category(db, category_id)
    row.status = "active"
    row.deprecated_reason = None
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def get_group_tree(db: AsyncSession, group_id: uuid.UUID) -> list[Category]:
    """Every item in the group, deprecated ones included.

    This feeds the management screen, where hiding deprecated rows would
    leave the admin unable to restore them.
    """
    await get_group(db, group_id)
    return list(
        (
            await db.execute(
                select(Category)
                .where(Category.group_id == group_id)
                .order_by(Category.order_index, Category.name)
            )
        ).scalars().all()
    )


async def list_by_group_code(db: AsyncSession, code: str) -> list[Category]:
    """What other features call. Deprecated items are excluded on purpose:
    a value that should no longer be chosen must not appear in a picker.
    """
    group = await get_group_by_code(db, code)
    return list(
        (
            await db.execute(
                select(Category)
                .where(Category.group_id == group.id, Category.status == "active")
                .order_by(Category.order_index, Category.name)
            )
        ).scalars().all()
    )
