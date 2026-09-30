"""Provider-agnostic OAuth/SSO helper (Google, Microsoft, TGSSO via OIDC)."""
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_client

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, dict] = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
    },
    "microsoft": {
        "auth_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "scope": "openid email profile",
    },
    "tgsso": {
        # All endpoints come from env vars (custom OIDC)
        "scope": "openid email profile",
    },
}

_STATE_TTL = 300  # 5 minutes


def _get_provider_config(provider: str, settings) -> dict:
    """Return merged provider config with values from settings."""
    cfg = dict(PROVIDERS[provider])

    if provider == "google":
        cfg["client_id"] = settings.GOOGLE_CLIENT_ID
        cfg["client_secret"] = settings.GOOGLE_CLIENT_SECRET
        cfg["redirect_uri"] = settings.GOOGLE_REDIRECT_URI

    elif provider == "microsoft":
        tenant = settings.MICROSOFT_TENANT_ID or "common"
        cfg["auth_url"] = cfg["auth_url"].replace("{tenant}", tenant)
        cfg["token_url"] = cfg["token_url"].replace("{tenant}", tenant)
        cfg["client_id"] = settings.MICROSOFT_CLIENT_ID
        cfg["client_secret"] = settings.MICROSOFT_CLIENT_SECRET
        cfg["redirect_uri"] = settings.MICROSOFT_REDIRECT_URI

    elif provider == "tgsso":
        cfg["auth_url"] = settings.TGSSO_AUTH_URL
        cfg["token_url"] = settings.TGSSO_TOKEN_URL
        cfg["userinfo_url"] = settings.TGSSO_USERINFO_URL
        cfg["client_id"] = settings.TGSSO_CLIENT_ID
        cfg["client_secret"] = settings.TGSSO_CLIENT_SECRET
        cfg["redirect_uri"] = settings.TGSSO_REDIRECT_URI

    return cfg


def is_provider_configured(provider: str, settings) -> bool:
    """Return True if the provider has a non-empty client_id."""
    cfg = _get_provider_config(provider, settings)
    return bool(cfg.get("client_id"))


async def get_oauth_redirect_url(provider: str, settings) -> str:
    """Generate the authorization URL and persist state in Redis (5 min TTL)."""
    cfg = _get_provider_config(provider, settings)
    state = str(uuid.uuid4())
    await redis_client.setex(f"oauth_state:{state}", _STATE_TTL, provider)

    import urllib.parse

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
    }
    # Google requires access_type for offline access
    if provider == "google":
        params["access_type"] = "online"

    return cfg["auth_url"] + "?" + urllib.parse.urlencode(params)


async def handle_oauth_callback(
    provider: str,
    code: str,
    state: str,
    db: AsyncSession,
    settings,
) -> tuple[str, str]:
    """
    Validate state, exchange code for tokens, fetch user info.
    Returns (jwt_access_token, raw_refresh_token).
    """
    from app.core.exceptions import AppException

    # 1. Validate state from Redis
    stored_provider = await redis_client.get(f"oauth_state:{state}")
    if not stored_provider:
        raise AppException("OAUTH_INVALID_STATE", "Invalid or expired OAuth state", 400)
    stored = stored_provider if isinstance(stored_provider, str) else stored_provider.decode()
    if stored != provider:
        raise AppException("OAUTH_INVALID_STATE", "State mismatch", 400)
    await redis_client.delete(f"oauth_state:{state}")

    cfg = _get_provider_config(provider, settings)

    # 2. Exchange code → access token
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            cfg["token_url"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg["redirect_uri"],
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise AppException(
                "OAUTH_TOKEN_EXCHANGE_FAILED",
                f"Token exchange failed: {token_resp.text[:200]}",
                400,
            )
        token_data = token_resp.json()
        provider_access_token = token_data.get("access_token")
        if not provider_access_token:
            raise AppException("OAUTH_TOKEN_EXCHANGE_FAILED", "No access_token in response", 400)

        # 3. Get user info
        userinfo_resp = await client.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {provider_access_token}"},
        )
        if userinfo_resp.status_code != 200:
            raise AppException(
                "OAUTH_USERINFO_FAILED",
                f"Userinfo request failed: {userinfo_resp.text[:200]}",
                400,
            )
        userinfo = userinfo_resp.json()

    # Normalize userinfo fields across providers
    email = (
        userinfo.get("email")
        or userinfo.get("mail")
        or userinfo.get("userPrincipalName", "")
    )
    name = (
        userinfo.get("name")
        or userinfo.get("displayName")
        or userinfo.get("givenName", "")
        or email.split("@")[0]
    )
    oauth_id = str(
        userinfo.get("sub")
        or userinfo.get("id")
        or userinfo.get("oid")
        or email
    )

    if not email:
        raise AppException("OAUTH_MISSING_EMAIL", "Provider did not return an email address", 400)

    # 4. Get or create user
    user = await get_or_create_oauth_user(db, email=email, name=name, provider=provider, oauth_id=oauth_id)

    # 5. Issue JWT + refresh token
    access_token, raw_refresh = await _issue_tokens(db, user)
    return access_token, raw_refresh


async def _issue_tokens(db: AsyncSession, user) -> tuple[str, str]:
    """Create and persist a JWT access token + refresh token for an OAuth user."""
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from app.core.security import create_access_token, create_raw_refresh_token
    from app.models.token import RefreshToken

    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    access_token, _jti = create_access_token(str(user.id))
    raw_refresh, refresh_hash = create_raw_refresh_token()

    refresh_token = RefreshToken(
        id=_uuid.uuid4(),
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=_now() + timedelta(days=7),
        ip_address=None,
        user_agent=None,
    )
    db.add(refresh_token)
    await db.commit()
    return access_token, raw_refresh


async def get_or_create_oauth_user(
    db: AsyncSession,
    email: str,
    name: str,
    provider: str,
    oauth_id: str,
):
    """Find user by email. If found, update OAuth fields. If not, create new active user."""
    from app.models.user import User

    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user:
        # Update oauth fields if not set or changed
        user.oauth_provider = provider
        user.oauth_id = oauth_id
        await db.commit()
        await db.refresh(user)
        return user

    # Create new user
    import uuid as _uuid

    new_user = User(
        id=_uuid.uuid4(),
        name=name,
        email=email,
        password_hash=None,
        status="active",
        is_verified=True,
        oauth_provider=provider,
        oauth_id=oauth_id,
    )
    db.add(new_user)
    await db.flush()

    # Assign default 'user' role
    from sqlalchemy import select as _select

    from app.models.rbac import Role, UserRole

    role_result = await db.execute(_select(Role).where(Role.slug == "user"))
    role = role_result.scalar_one_or_none()
    if role:
        db.add(UserRole(user_id=new_user.id, role_id=role.id))

    await db.commit()
    await db.refresh(new_user)
    return new_user
