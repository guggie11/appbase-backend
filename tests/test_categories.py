"""Category Management: generic reference data for other features.

The rules below are the ones that quietly rot a reference table: a code that
can be edited after other tables point at it, a deprecated value that still
shows up in pickers, a parent from a different group, a cycle.
"""
import uuid

import pytest
from sqlalchemy import select

from app.api.v1.categories import service
from app.core.exceptions import AppException
from app.models.category import Category, CategoryGroup
from app.schemas.category import (
    CreateCategoryGroupRequest,
    CreateCategoryRequest,
    UpdateCategoryGroupRequest,
    UpdateCategoryRequest,
)


async def _group(db, code="order-status", name="Order Status", is_system=False):
    group = CategoryGroup(
        id=uuid.uuid4(), code=code, name=name, is_system=is_system, is_active=True
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def _item(db, group, code, name=None, parent_id=None):
    row = Category(
        id=uuid.uuid4(),
        group_id=group.id,
        parent_id=parent_id,
        code=code,
        name=name or code.title(),
        status="active",
        order_index=0,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_code_must_be_unique(test_db):
    await service.create_group(
        test_db, CreateCategoryGroupRequest(name="Order Status", code="order-status")
    )
    with pytest.raises(AppException):
        await service.create_group(
            test_db, CreateCategoryGroupRequest(name="Another", code="order-status")
        )


@pytest.mark.asyncio
async def test_group_code_is_derived_from_the_name_when_omitted(test_db):
    group = await service.create_group(
        test_db, CreateCategoryGroupRequest(name="Document Type")
    )
    assert group.code == "document-type"


@pytest.mark.asyncio
async def test_group_code_cannot_be_changed(test_db):
    """Other tables reference the code; editing it breaks them silently.

    The payload carries a `code` the schema does not define, so this fails
    unless the service itself ignores it — not merely because the schema
    happens to drop the field today.
    """
    group = await service.create_group(
        test_db, CreateCategoryGroupRequest(name="Priority", code="priority")
    )
    payload = UpdateCategoryGroupRequest(name="Priority Level")
    object.__setattr__(payload, "code", "something-else")
    await service.update_group(test_db, group.id, payload)
    refreshed = (
        await test_db.execute(
            select(CategoryGroup).where(CategoryGroup.id == group.id)
        )
    ).scalar_one()
    assert refreshed.code == "priority"
    assert refreshed.name == "Priority Level"


@pytest.mark.asyncio
async def test_system_group_cannot_be_deleted(test_db):
    """Locked in the backend, not merely hidden in the UI."""
    group = await _group(test_db, code="sys-group", name="System", is_system=True)
    with pytest.raises(AppException) as exc:
        await service.delete_group(test_db, group.id)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_group_with_categories_cannot_be_deleted(test_db):
    group = await _group(test_db, code="has-items")
    await _item(test_db, group, "draft")
    with pytest.raises(AppException) as exc:
        await service.delete_group(test_db, group.id)
    assert exc.value.status_code in (400, 409)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_is_unique_within_a_group_only(test_db):
    """Two groups may both have a "draft"; one group may not have two."""
    a = await _group(test_db, code="group-a")
    b = await _group(test_db, code="group-b")

    await service.create_category(
        test_db, CreateCategoryRequest(group_id=a.id, name="Draft", code="draft")
    )
    # Same code, different group — allowed.
    await service.create_category(
        test_db, CreateCategoryRequest(group_id=b.id, name="Draft", code="draft")
    )
    # Same code, same group — refused.
    with pytest.raises(AppException):
        await service.create_category(
            test_db, CreateCategoryRequest(group_id=a.id, name="Draft 2", code="draft")
        )


@pytest.mark.asyncio
async def test_category_code_cannot_be_changed(test_db):
    group = await _group(test_db, code="immutable-code")
    row = await _item(test_db, group, "pending")
    await service.update_category(
        test_db, row.id, UpdateCategoryRequest(name="Pending Review")
    )
    refreshed = (
        await test_db.execute(select(Category).where(Category.id == row.id))
    ).scalar_one()
    assert refreshed.code == "pending"
    assert refreshed.name == "Pending Review"


@pytest.mark.asyncio
async def test_parent_must_be_in_the_same_group(test_db):
    """A tree spanning groups is not a tree anyone can reason about."""
    a = await _group(test_db, code="tree-a")
    b = await _group(test_db, code="tree-b")
    outsider = await _item(test_db, b, "outsider")

    with pytest.raises(AppException):
        await service.create_category(
            test_db,
            CreateCategoryRequest(
                group_id=a.id, name="Child", code="child", parent_id=outsider.id
            ),
        )


@pytest.mark.asyncio
async def test_category_cannot_be_its_own_parent(test_db):
    group = await _group(test_db, code="self-parent")
    row = await _item(test_db, group, "node")
    with pytest.raises(AppException):
        await service.update_category(
            test_db, row.id, UpdateCategoryRequest(parent_id=row.id)
        )


@pytest.mark.asyncio
async def test_a_cycle_is_refused(test_db):
    """A -> B -> A would make the tree infinite."""
    group = await _group(test_db, code="cycle")
    a = await _item(test_db, group, "a")
    b = await _item(test_db, group, "b", parent_id=a.id)

    with pytest.raises(AppException):
        await service.update_category(
            test_db, a.id, UpdateCategoryRequest(parent_id=b.id)
        )


@pytest.mark.asyncio
async def test_depth_is_not_capped(test_db):
    """Nesting is free; an arbitrary limit belongs to a product, not here."""
    group = await _group(test_db, code="deep")
    parent = None
    for level in range(6):
        parent = await service.create_category(
            test_db,
            CreateCategoryRequest(
                group_id=group.id,
                name=f"Level {level}",
                code=f"level-{level}",
                parent_id=parent.id if parent else None,
            ),
        )
    assert parent is not None


# ---------------------------------------------------------------------------
# Deprecate / restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deprecate_requires_a_reason(test_db):
    """"Why was this switched off" is the first question six months later."""
    group = await _group(test_db, code="dep-reason")
    row = await _item(test_db, group, "legacy")
    with pytest.raises((AppException, ValueError)):
        await service.deprecate_category(test_db, row.id, reason="")


@pytest.mark.asyncio
async def test_deprecate_keeps_the_row_and_records_why(test_db):
    group = await _group(test_db, code="dep-keep")
    row = await _item(test_db, group, "old")
    await service.deprecate_category(test_db, row.id, reason="replaced by 'new'")

    refreshed = (
        await test_db.execute(select(Category).where(Category.id == row.id))
    ).scalar_one()
    assert refreshed.status == "deprecated"
    assert refreshed.deprecated_reason == "replaced by 'new'"


@pytest.mark.asyncio
async def test_deprecated_items_are_hidden_from_other_features(test_db):
    """by-group feeds pickers elsewhere; a deprecated value must not appear."""
    group = await _group(test_db, code="picker")
    keep = await _item(test_db, group, "keep")
    drop = await _item(test_db, group, "drop")
    await service.deprecate_category(test_db, drop.id, reason="no longer used")

    visible = await service.list_by_group_code(test_db, "picker")
    codes = {c.code for c in visible}
    assert keep.code in codes
    assert drop.code not in codes


@pytest.mark.asyncio
async def test_deprecated_items_still_appear_in_management(test_db):
    """Hidden from pickers, not from the admin who has to manage them."""
    group = await _group(test_db, code="mgmt")
    row = await _item(test_db, group, "gone")
    await service.deprecate_category(test_db, row.id, reason="superseded")

    tree = await service.get_group_tree(test_db, group.id)
    assert any(node.id == row.id for node in tree)


@pytest.mark.asyncio
async def test_restore_brings_it_back(test_db):
    group = await _group(test_db, code="restore")
    row = await _item(test_db, group, "back")
    await service.deprecate_category(test_db, row.id, reason="temporary")
    await service.restore_category(test_db, row.id)

    refreshed = (
        await test_db.execute(select(Category).where(Category.id == row.id))
    ).scalar_one()
    assert refreshed.status == "active"
    assert refreshed.deprecated_reason is None


@pytest.mark.asyncio
async def test_system_category_cannot_be_deleted_but_can_be_deprecated(test_db):
    group = await _group(test_db, code="sys-item")
    row = await _item(test_db, group, "builtin")
    row.is_system = True
    await test_db.commit()

    with pytest.raises(AppException) as exc:
        await service.delete_category(test_db, row.id)
    assert exc.value.status_code == 403

    await service.deprecate_category(test_db, row.id, reason="retired")
    refreshed = (
        await test_db.execute(select(Category).where(Category.id == row.id))
    ).scalar_one()
    assert refreshed.status == "deprecated"


@pytest.mark.asyncio
async def test_category_with_children_cannot_be_deleted(test_db):
    group = await _group(test_db, code="has-children")
    parent = await _item(test_db, group, "parent")
    await _item(test_db, group, "child", parent_id=parent.id)

    with pytest.raises(AppException):
        await service.delete_category(test_db, parent.id)


# ---------------------------------------------------------------------------
# The template ships empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeding_creates_no_groups(test_db):
    """Appbase is a template: the vocabulary belongs to the project using it.

    The suite shares a database, so count the delta rather than expecting an
    empty table — other tests create groups of their own.
    """
    from app.core.seed import seed_permissions, seed_roles, seed_settings

    before = len((await test_db.execute(select(CategoryGroup))).scalars().all())

    await seed_permissions(test_db)
    await seed_roles(test_db)
    await seed_settings(test_db)

    after = len((await test_db.execute(select(CategoryGroup))).scalars().all())
    assert after == before, f"seeding added {after - before} group(s)"
