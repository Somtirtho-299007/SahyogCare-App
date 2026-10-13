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
    # Extra areas this deployment serves, comma-separated. Every area with a district
    # office passphrase in app/offices.py is served anyway, so this is normally left alone.
    # Each area is fully separate: its coordinator sees only its own people, hospitals and referrals.
    districts: str = "Nadia,Naihati"
    # Area given to coordinators listed without one (see coordinator_entries).
    coordinator_district: str = "Nadia"
    # Anyone may sign up with their email. ASHAs (who only ever see their own patients)
    # can be approved automatically; hospital staff, doctors and coordinators always
    # need a coordinator's approval because they see other people's patients.
    auto_approve_asha: bool = False

    # District office passphrases are built in (app/offices.py). This optional setting
    # can add or override one on the server: "Area:passphrase,Area2:passphrase".
    office_passphrases: str = ""

    # Fake demo hospitals and @sahyogcare.test accounts. Set to false on the live
    # server: the demo hospitals are then hidden and the demo accounts switched off.
    demo_data: bool = True

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
    def district_list(self) -> list[str]:
        from app.offices import OFFICES  # every area with a district office is served

        areas = [d.strip() for d in self.districts.split(",") if d.strip()]
        for name in OFFICES:
            if name.lower() not in {a.lower() for a in areas}:
                areas.append(name)
        return areas

    def canonical_district(self, name: str | None) -> str | None:
        """The configured spelling of an area name, or None when it is not served here."""
        if not name:
            return None
        return next((d for d in self.district_list if d.lower() == name.strip().lower()), None)

    def office_passphrase(self, area: str) -> str | None:
        for item in self.office_passphrases.split(","):
            name, _, phrase = item.strip().partition(":")
            if name.strip().lower() == area.lower() and phrase.strip():
                return phrase.strip()
        return None

    @property
    def coordinator_entries(self) -> list[tuple[str, str]]:
        """SAHYOG_COORDINATOR_EMAILS as (email, area): "a@gmail.com:Nadia,b@gmail.com:Naihati".
        An entry without ":Area" gets coordinator_district."""
        out = []
        for item in self.coordinator_emails.split(","):
            email, _, area = item.strip().partition(":")
            if email.strip():
                out.append((email.strip().lower(),
                            self.canonical_district(area) or self.canonical_district(self.coordinator_district)
                            or self.coordinator_district))
        return out

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

if settings.environment == "production" and (
    settings.secret_key == "dev-only-secret-change-me-before-production" or len(settings.secret_key) < 32
):
    raise RuntimeError("Set SAHYOG_SECRET_KEY to a random value of at least 32 characters in production.")
