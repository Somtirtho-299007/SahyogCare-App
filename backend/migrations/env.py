"""Alembic environment: uses the app's own database settings and table definitions."""

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.db import Base, engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with engine.connect() as conn:
        _run(conn)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot alter tables in place; batch mode copies the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not used in this project.")
run_migrations_online()
