"""Shared pytest fixtures for all tests.

Uses SQLite in-memory (aiosqlite) + fakeredis so no live DB/Redis is needed.
"""
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base

# ---------------------------------------------------------------------------
# Shared SQLite engine (one per test session; tables created once)
# ---------------------------------------------------------------------------
TEST_DB_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(
    TEST_DB_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

TestSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Create all tables before any test, drop after the session
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    # Import all models so metadata is populated
    import app.models.audit  # noqa: F401
    import app.models.menu  # noqa: F401
    import app.models.rbac  # noqa: F401
    import app.models.token  # noqa: F401
    import app.models.user  # noqa: F401

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Per-test DB session + dependency override
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean async session per test (rolls back after)."""
    async with TestSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Fake redis fixture
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(autouse=True)
async def fake_redis(monkeypatch):
    """Replace the global redis_client with fakeredis for every test."""
    import app.core.redis as redis_module
    import app.api.deps as deps_module

    fake = fake_aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_module, "redis_client", fake)
    monkeypatch.setattr(deps_module, "redis_client", fake, raising=False)
    yield fake
    await fake.flushall()
    await fake.aclose()


# ---------------------------------------------------------------------------
# FastAPI test app with overrides
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
async def async_client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient wired to the FastAPI app with test DB + fake redis."""
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    from app.main import app
    from app.api.deps import get_db
    import app.api.v1.auth.router as auth_router_module

    # Override DB
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    # Disable rate limiting in tests (both app state and per-router limiters)
    original_app_limiter = app.state.limiter
    original_auth_limiter_enabled = auth_router_module.limiter.enabled

    test_limiter = Limiter(key_func=get_remote_address, enabled=False)
    app.state.limiter = test_limiter
    auth_router_module.limiter.enabled = False

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.state.limiter = original_app_limiter
    auth_router_module.limiter.enabled = original_auth_limiter_enabled
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper: create a user directly in the DB
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
def create_test_user(test_db: AsyncSession):
    """Factory fixture: await create_test_user(email, password, **kwargs)."""
    from app.core.security import hash_password
    from app.models.user import User

    async def _create(
        email: str = "test@example.com",
        password: str = "P@ssw0rd!123",
        name: str = "Test User",
        status: str = "active",
        is_verified: bool = True,
        locked_until: datetime | None = None,
        failed_login_count: int = 0,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            name=name,
            email=email,
            password_hash=hash_password(password),
            status=status,
            is_verified=is_verified,
            locked_until=locked_until,
            failed_login_count=failed_login_count,
        )
        test_db.add(user)
        await test_db.commit()
        await test_db.refresh(user)
        return user

    return _create


# ---------------------------------------------------------------------------
# Helper: get auth headers for a user
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
def auth_headers():
    """Factory: auth_headers(user) -> Authorization Bearer header dict."""
    from app.core.security import create_access_token

    def _headers(user) -> dict[str, str]:
        token, _ = create_access_token(str(user.id))
        return {"Authorization": f"Bearer {token}"}

    return _headers


# ---------------------------------------------------------------------------
# Helper: create role + permission + assign to user
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture()
def create_role(test_db: AsyncSession):
    """Factory: await create_role(slug, permissions=[...]) -> Role."""
    from app.models.rbac import Permission, Role, RolePermission

    async def _create(
        slug: str,
        name: str = "",
        permissions: list[str] | None = None,
    ):
        from sqlalchemy import select

        # Reuse an existing role: the seed now creates super-admin and user,
        # so a blind insert collides on roles.slug.
        existing = await test_db.execute(select(Role).where(Role.slug == slug))
        role = existing.scalar_one_or_none()
        if role is None:
            role = Role(
                id=uuid.uuid4(),
                name=name or slug,
                slug=slug,
                is_system=False,
                is_active=True,
            )
            test_db.add(role)
            await test_db.flush()

        for perm_slug in permissions or []:
            # upsert permission
            from sqlalchemy import select

            r = await test_db.execute(
                select(Permission).where(Permission.slug == perm_slug)
            )
            perm = r.scalar_one_or_none()
            if not perm:
                perm = Permission(
                    id=uuid.uuid4(),
                    name=perm_slug,
                    slug=perm_slug,
                    module=perm_slug.split(".")[0],
                    action=perm_slug.split(".")[1] if "." in perm_slug else "access",
                )
                test_db.add(perm)
                await test_db.flush()

            rp = RolePermission(role_id=role.id, permission_id=perm.id)
            test_db.add(rp)

        await test_db.commit()
        await test_db.refresh(role)
        return role

    return _create


@pytest_asyncio.fixture()
def assign_role(test_db: AsyncSession):
    """Factory: await assign_role(user, role) -> None."""
    from app.models.rbac import UserRole

    async def _assign(user, role):
        ur = UserRole(user_id=user.id, role_id=role.id)
        test_db.add(ur)
        await test_db.commit()

    return _assign
