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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]


settings = Settings()
