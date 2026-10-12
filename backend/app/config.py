"""Settings read from environment variables (or a local .env file)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SAHYOG_", extra="ignore")

    # Local development uses a SQLite file; production sets a PostgreSQL URL,
    # e.g. postgresql+psycopg://user:password@host:5432/sahyogcare
    database_url: str = "sqlite:///./sahyogcare.db"

    # Comma-separated list of frontend origins allowed to call the API.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # "development" or "production". Production refuses to start with the default secret.
    environment: str = "development"
    secret_key: str = "dev-only-change-me"

    @property
    def database_url_for_sqlalchemy(self) -> str:
        # Render and most hosts hand out "postgres://" or "postgresql://" URLs; use the psycopg 3 driver.
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

if settings.environment == "production" and settings.secret_key == "dev-only-change-me":
    raise RuntimeError("Set SAHYOG_SECRET_KEY before running in production.")
