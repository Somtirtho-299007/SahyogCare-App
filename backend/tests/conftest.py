import os
import sys
from pathlib import Path

import pytest

# Each test run uses its own throwaway SQLite file, never the developer's database.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEST_DB = Path(__file__).resolve().parent / "_test.db"
# Set SAHYOG_TEST_DATABASE_URL to run the same tests against PostgreSQL.
os.environ["SAHYOG_WATCHDOG_ENABLED"] = "false"  # tests run the watchdog by hand
os.environ["SAHYOG_DATABASE_URL"] = os.environ.get("SAHYOG_TEST_DATABASE_URL", f"sqlite:///{TEST_DB}")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
        yield session


@pytest.fixture()
def client(db):
    from app.routers.public import lookup_limiter

    lookup_limiter.reset()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(db):
    """auth("WORKER") -> headers for the seeded test user with that role."""
    from sqlalchemy import select

    from app.models import User
    from app.security import access_token_for

    def _headers(role: str) -> dict[str, str]:
        user = db.scalar(select(User).where(User.role == role))
        return {"Authorization": f"Bearer {access_token_for(user)}"}

    return _headers


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)
