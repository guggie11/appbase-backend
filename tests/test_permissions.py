"""S-076 — Unit tests for permission guard (require_permission + blacklist)."""


class TestPermissions:
    async def test_permission_granted(
        self,
        async_client,
        create_test_user,
        create_role,
        assign_role,
        auth_headers,
    ):
        """User with users.read permission can access GET /api/v1/users/."""
        user = await create_test_user(email="granted@example.com")
        role = await create_role("editor", permissions=["users.read"])
        await assign_role(user, role)

        resp = await async_client.get("/api/v1/users/", headers=auth_headers(user))
        assert resp.status_code == 200

    async def test_permission_denied(
        self,
        async_client,
        create_test_user,
        create_role,
        assign_role,
        auth_headers,
    ):
        """User without users.read permission gets 403 FORBIDDEN."""
        user = await create_test_user(email="denied@example.com")
        # Assign a role with no permissions
        role = await create_role("viewer-noperms", permissions=[])
        await assign_role(user, role)

        resp = await async_client.get("/api/v1/users/", headers=auth_headers(user))
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"

    async def test_superadmin_bypass(
        self,
        async_client,
        create_test_user,
        create_role,
        assign_role,
        auth_headers,
    ):
        """super-admin role bypasses all permission checks."""
        user = await create_test_user(email="superadmin@example.com")
        role = await create_role("super-admin", permissions=[])
        await assign_role(user, role)

        resp = await async_client.get("/api/v1/users/", headers=auth_headers(user))
        assert resp.status_code == 200

    async def test_blacklisted_token(
        self,
        async_client,
        create_test_user,
        fake_redis,
    ):
        """Token in blacklist returns 401."""
        user = await create_test_user(email="blacklisted@example.com")

        # Login to get a real token+jti
        login_r = await async_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "P@ssw0rd!123"},
        )
        assert login_r.status_code == 200
        token = login_r.json()["data"]["access_token"]

        # Decode JTI and blacklist it
        from app.core.security import decode_token

        payload = decode_token(token)
        jti = payload["jti"]
        await fake_redis.setex(f"blacklist:{jti}", 3600, "1")

        resp = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
