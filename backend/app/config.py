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
    secret_key: str = "dev-only-secret-change-me-before-production"

    # Background job that flags silent referrals and overdue follow-ups.
    watchdog_enabled: bool = True

    access_token_minutes: int = 15
    refresh_token_days: int = 7

    # Email for one-time codes. If smtp_host is empty, codes are printed in the
    # server log instead (development only).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "SahyogCare <no-reply@sahyogcare.test>"

    # When no SMTP server is set, write login codes to the server log instead of
    # failing. Lets a demo deployment work before email is configured; the code
    # is only visible to whoever can read the server logs, never sent to the browser.
    log_login_codes: bool = False

    # Brevo (brevo.com) email API key. Sends over HTTPS, so it works on hosts that
    # block SMTP ports (Render's free plan does). Used instead of SMTP when set.
    brevo_api_key: str = ""

    # Real email addresses (comma-separated) that are made coordinators when the
    # server starts. The coordinator then adds every other user from the app.
    coordinator_emails: str = ""
    # District given to coordinators from the setting above and to people who sign up.
    coordinator_district: str = "Nadia"
    # Anyone may sign up with their email. ASHAs (who only ever see their own patients)
    # can be approved automatically; hospital staff, doctors and coordinators always
    # need a coordinator's approval because they see other people's patients.
    auto_approve_asha: bool = False

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def database_url_for_sqlalchemy(self) -> str:
        # Render and most hosts hand out "postgres://" or "postgresql://" URLs; use the psycopg 3 driver.
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def coordinator_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.coordinator_emails.split(",") if e.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

if settings.environment == "production" and (
    settings.secret_key == "dev-only-secret-change-me-before-production" or len(settings.secret_key) < 32
):
    raise RuntimeError("Set SAHYOG_SECRET_KEY to a random value of at least 32 characters in production.")
