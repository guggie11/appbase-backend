"""S-075 — Unit tests for auth endpoints."""
from datetime import UTC, datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------
class TestRegister:
    async def test_register_success(self, async_client, test_db):
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={"name": "Alice", "email": "alice@example.com", "password": "P@ssw0rd!123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["email"] == "alice@example.com"

    async def test_register_duplicate_email(self, async_client, test_db):
        payload = {"name": "Bob", "email": "bob@example.com", "password": "P@ssw0rd!123"}
        r1 = await async_client.post("/api/v1/auth/register", json=payload)
        assert r1.status_code == 200
        r2 = await async_client.post("/api/v1/auth/register", json=payload)
        assert r2.status_code == 409

    async def test_register_weak_password(self, async_client, test_db):
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={"name": "Carol", "email": "carol@example.com", "password": "weak"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class TestLogin:
    async def test_login_success(self, async_client, create_test_user):
        user = await create_test_user(email="loginok@example.com", password="P@ssw0rd!123")
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()["data"]

    async def test_login_wrong_password(self, async_client, create_test_user):
        user = await create_test_user(email="wrong@example.com", password="P@ssw0rd!123")
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "WrongPass!999"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"

    async def test_login_unverified(self, async_client, create_test_user):
        user = await create_test_user(
            email="unverified@example.com",
            password="P@ssw0rd!123",
            is_verified=False,
            status="pending",
        )
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "AUTH_EMAIL_NOT_VERIFIED"

    async def test_login_account_locked(self, async_client, create_test_user):
        locked_until = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
        user = await create_test_user(
            email="locked@example.com",
            password="P@ssw0rd!123",
            locked_until=locked_until,
        )
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "AUTH_ACCOUNT_LOCKED"


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------
class TestLockout:
    async def test_lockout_after_5_failures(self, async_client, create_test_user):
        user = await create_test_user(email="lockme@example.com", password="P@ssw0rd!123")
        # 5 failed attempts
        for _ in range(5):
            r = await async_client.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": "WrongPass!999"},
            )
            assert r.status_code == 401

        # 6th attempt — account should be locked
        r6 = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert r6.status_code == 423
        assert r6.json()["error"]["code"] == "AUTH_ACCOUNT_LOCKED"


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
class TestLogout:
    async def test_logout_success(self, async_client, create_test_user, auth_headers):
        user = await create_test_user(email="logout@example.com", password="P@ssw0rd!123")
        # Login first to get cookie + csrf_token
        login_r = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert login_r.status_code == 200
        csrf_token = login_r.cookies.get("csrf_token", "")
        headers = {**auth_headers(user), "X-CSRF-Token": csrf_token}
        resp = await async_client.post("/api/v1/auth/logout", headers=headers)
        assert resp.status_code == 200

    async def test_logout_blacklists_token(self, async_client, create_test_user, auth_headers):
        user = await create_test_user(email="blacklist@example.com", password="P@ssw0rd!123")
        login_r = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert login_r.status_code == 200
        token = login_r.json()["data"]["access_token"]
        csrf_token = login_r.cookies.get("csrf_token", "")
        bearer = {"Authorization": f"Bearer {token}", "X-CSRF-Token": csrf_token}

        # Logout
        logout_r = await async_client.post("/api/v1/auth/logout", headers=bearer)
        assert logout_r.status_code == 200

        # Use old token — should be 401
        me_r = await async_client.get("/api/v1/auth/me", headers=bearer)
        assert me_r.status_code == 401


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------
class TestRefresh:
    async def test_refresh_success(self, async_client, create_test_user):
        user = await create_test_user(email="refresh@example.com", password="P@ssw0rd!123")
        login_r = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert login_r.status_code == 200
        # Cookie is set automatically by httpx
        refresh_r = await async_client.post("/api/v1/auth/refresh")
        assert refresh_r.status_code == 200
        assert "access_token" in refresh_r.json()["data"]

    async def test_refresh_reuse(self, async_client, create_test_user):
        user = await create_test_user(email="reuse@example.com", password="P@ssw0rd!123")
        login_r = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert login_r.status_code == 200

        # First refresh — success
        r1 = await async_client.post("/api/v1/auth/refresh")
        assert r1.status_code == 200

        # Use the ORIGINAL refresh token again — simulate reuse by sending it manually
        # The cookie was replaced after first refresh; grab original from login
        original_rt = login_r.cookies.get("refresh_token")
        if not original_rt:
            pytest.skip("No refresh_token cookie returned by login")

        r2 = await async_client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": original_rt},
        )
        # Should be 401 (revoked) — all sessions invalidated
        assert r2.status_code == 401


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------
class TestMe:
    async def test_me_authenticated(self, async_client, create_test_user, auth_headers):
        user = await create_test_user(email="me@example.com", password="P@ssw0rd!123")
        resp = await async_client.get("/api/v1/auth/me", headers=auth_headers(user))
        assert resp.status_code == 200
        assert resp.json()["data"]["email"] == user.email

    async def test_me_unauthenticated(self, async_client):
        resp = await async_client.get("/api/v1/auth/me")
        assert resp.status_code == 401
