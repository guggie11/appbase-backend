from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Appbase"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql+psycopg://appbase:appbase@localhost:5432/appbase"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "changeme-generate-a-long-random-string"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: str = "http://localhost:5173"

    # Added Phase 1
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    FRONTEND_URL: str = "http://localhost:5173"
    ALGORITHM: str = "HS256"

    # OAuth / SSO (C2) — all optional, empty = provider disabled
    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/google/callback"

    # Microsoft OAuth
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/microsoft/callback"
    MICROSOFT_TENANT_ID: str = "common"

    # TGSSO (Telkom SSO — standard OIDC)
    TGSSO_CLIENT_ID: str = ""
    TGSSO_CLIENT_SECRET: str = ""
    TGSSO_AUTH_URL: str = ""
    TGSSO_TOKEN_URL: str = ""
    TGSSO_USERINFO_URL: str = ""
    TGSSO_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/oauth/tgsso/callback"

    # Frontend redirect URLs after OAuth
    OAUTH_SUCCESS_REDIRECT: str = "http://localhost:5173/oauth/callback"
    OAUTH_ERROR_REDIRECT: str = "http://localhost:5173/oauth/error"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]


settings = Settings()
