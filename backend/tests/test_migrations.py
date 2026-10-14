"""The migrations must build exactly the tables the app defines, and adopt old databases."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db import Base, engine
from app.migrate import _config, run_migrations
from conftest import reset_database


def _head() -> str:
    with engine.connect() as conn:
        return ScriptDirectory.from_config(_config(conn)).get_current_head()


def _current() -> str:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def test_migrations_match_the_models(db):
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"Add a migration for: {diff}"
    assert _current() == _head()


def test_running_again_changes_nothing(db):
    run_migrations()
    assert _current() == _head()


def test_old_database_without_versions_is_adopted(db):
    # A database made before migrations existed: tables as of 0001, no version table.
    reset_database()
    from alembic import command

    with engine.begin() as conn:
        command.downgrade(_config(conn), "0001")
        conn.execute(text("DROP TABLE alembic_version"))
    assert "bed_wards" not in inspect(engine).get_table_names()

    run_migrations()
    assert "bed_wards" in inspect(engine).get_table_names()
    assert _current() == _head()
