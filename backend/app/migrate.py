"""Brings the database up to date with every migration in migrations/versions.

Runs automatically when the server starts (app/main.py) and when seeding
(`python -m app.seed`), so a deploy upgrades the live database by itself and
keeps its data. Can also be run by hand:  python -m app.migrate

Databases created before migrations existed (tables made directly by the app)
are recognised and marked with the version they already match, then upgraded.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.db import engine

log = logging.getLogger("sahyogcare.migrate")
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def _config(connection) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False
    return cfg


def _version_of_old_database(tables: set[str]) -> str | None:
    """Which migration an unversioned database already matches (None = empty database)."""
    if "facilities" not in tables:
        return None
    if "bed_wards" in tables:
        return "0002"
    return "0001"


def run_migrations() -> None:
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables:
            existing = _version_of_old_database(tables)
            if existing is not None:
                log.info("Existing database matches migration %s; marking it.", existing)
                command.stamp(_config(connection), existing)
        command.upgrade(_config(connection), "head")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migrations()
    print("Database is up to date.")
