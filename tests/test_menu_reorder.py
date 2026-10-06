"""Menu mutation regressions using a real isolated async ORM session."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.menus import service
from app.api.v1.menus.router import menu_to_response
from app.core.exceptions import AppException
from app.models.base import Base
from app.models.menu import Menu, MenuRole
from app.models.rbac import Role


@pytest.fixture
async def test_db(fake_redis, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(service, "redis_client", fake_redis)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


@pytest.fixture
async def menu_with_role(test_db):
    role = Role(id=uuid.uuid4(), name="Menu viewer", slug="menu-viewer")
    menu = Menu(id=uuid.uuid4(), label="Dashboard", order_index=7)
    test_db.add_all([role, menu])
    await test_db.flush()
    test_db.add(MenuRole(menu_id=menu.id, role_id=role.id))
    await test_db.commit()
    ids = (menu.id, role.id)
    test_db.expunge_all()  # Do not mask missing eager loads with the identity map.
    return ids


async def test_legacy_order_returns_serializable_roles(test_db, menu_with_role):
    menu_id, role_id = menu_with_role
    menu = await service.update_menu_order(test_db, menu_id, 0)
    response = menu_to_response(menu)
    assert response.order_index == 0
    assert [role.id for role in response.roles] == [role_id]


@pytest.fixture
async def sibling_group(test_db):
    """Roots with duplicate/non-contiguous order_index, plus one child."""
    parent = Menu(id=uuid.uuid4(), label="Administration", order_index=5)
    a = Menu(id=uuid.uuid4(), label="Profile", order_index=0)
    b = Menu(id=uuid.uuid4(), label="Dashboard", order_index=1)
    c = Menu(id=uuid.uuid4(), label="Menus", order_index=1)
    child = Menu(id=uuid.uuid4(), label="Users", parent_id=parent.id, order_index=1)
    test_db.add_all([parent, a, b, c, child])
    await test_db.commit()
    ids = (parent.id, a.id, b.id, c.id, child.id)
    test_db.expunge_all()
    return ids


async def test_reorder_siblings_normalises_duplicate_indices(test_db, sibling_group):
    parent_id, a_id, b_id, c_id, child_id = sibling_group
    # Move the first root to the end; stored indices contain duplicates (1, 1).
    desired = [b_id, c_id, parent_id, a_id]

    menus = await service.reorder_siblings(test_db, parent_id=None, menu_ids=desired)

    roots = [m for m in menus if m.parent_id is None]
    assert [m.id for m in sorted(roots, key=lambda m: m.order_index)] == desired
    assert [m.order_index for m in sorted(roots, key=lambda m: m.order_index)] == [0, 1, 2, 3]
    # Hierarchy is untouched: the child keeps its parent.
    child = next(m for m in menus if m.id == child_id)
    assert child.parent_id == parent_id
    # Serialising the result must not need lazy IO.
    assert all(menu_to_response(m) is not None for m in menus)


async def test_reorder_rejects_incomplete_sibling_set_without_writing(test_db, sibling_group):
    parent_id, a_id, b_id, c_id, _child_id = sibling_group

    with pytest.raises(AppException) as exc_info:
        await service.reorder_siblings(test_db, parent_id=None, menu_ids=[b_id, a_id])

    assert exc_info.value.status_code == 422
    await test_db.rollback()
    remaining = await service.list_menus(test_db)
    by_id = {m.id: m.order_index for m in remaining}
    assert by_id[a_id] == 0 and by_id[b_id] == 1 and by_id[c_id] == 1


async def test_reorder_rejects_duplicate_ids(test_db, sibling_group):
    parent_id, a_id, b_id, c_id, _child_id = sibling_group

    with pytest.raises(AppException) as exc_info:
        await service.reorder_siblings(
            test_db, parent_id=None, menu_ids=[a_id, a_id, b_id, c_id, parent_id]
        )

    assert exc_info.value.status_code == 422


async def test_reorder_rejects_foreign_parent_member(test_db, sibling_group):
    parent_id, a_id, b_id, c_id, child_id = sibling_group

    # child_id belongs to parent_id, not to the root group.
    with pytest.raises(AppException) as exc_info:
        await service.reorder_siblings(
            test_db, parent_id=None, menu_ids=[a_id, b_id, c_id, parent_id, child_id]
        )

    assert exc_info.value.status_code == 422
