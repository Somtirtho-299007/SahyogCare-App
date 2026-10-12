import os
import sys
from pathlib import Path

import pytest

# Each test run uses its own throwaway SQLite file, never the developer's database.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEST_DB = Path(__file__).resolve().parent / "_test.db"
os.environ["SAHYOG_DATABASE_URL"] = f"sqlite:///{TEST_DB}"

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
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)
