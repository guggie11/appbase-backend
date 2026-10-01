"""Regression: create_menu must return a fully serialisable menu.

Mirrors the MissingGreenlet class already fixed for update/order/roles.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.menus import service
from app.api.v1.menus.router import menu_to_response
from app.models.base import Base
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


async def test_create_menu_with_roles_is_serialisable(test_db):
    role = Role(id=uuid.uuid4(), name="Editor", slug="editor")
    test_db.add(role)
    await test_db.commit()
    test_db.expunge_all()  # Do not let the identity map mask a missing load.

    menu = await service.create_menu(
        test_db,
        label="Reports",
        icon="chart",
        path="/reports",
        parent_id=None,
        order_index=0,
        is_active=True,
        role_ids=[role.id],
    )

    response = menu_to_response(menu)
    assert response.label == "Reports"
    assert [r.slug for r in response.roles] == ["editor"]
