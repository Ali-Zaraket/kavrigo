"""Alembic environment.

Migrations run as the *owning* role (the one that can create tables), while the application
connects as a separate, non-superuser role that is subject to row-level security. Keeping those
apart is what makes RLS meaningful: a superuser or table owner without ``FORCE ROW LEVEL
SECURITY`` bypasses every policy silently.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from kavrigo_api.db.models import SCHEMA, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.getenv("POSTGRES_MIGRATION_DSN") or os.getenv("POSTGRES_DSN")
    if not url:
        raise RuntimeError(
            "POSTGRES_DSN (or POSTGRES_MIGRATION_DSN) must be set; migrations do not carry a "
            "hard-coded connection string"
        )
    return url


def _include_object(obj: object, name: str | None, type_: str, *_: object) -> bool:
    """Autogenerate only within our schema, so extensions and system objects are left alone."""
    if type_ == "table":
        return getattr(obj, "schema", None) == SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table_schema=SCHEMA,
        include_object=_include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    # Alembic writes its version table into `version_table_schema`, which it does *before*
    # running migration 0001 — the migration that creates the schema. Creating it here breaks
    # that cycle and keeps migrations runnable against an empty database.
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema=SCHEMA,
        include_object=_include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    # `engine.begin()`, not `engine.connect()`: SQLAlchemy 2.0 has no autocommit, and the
    # pre-migration CREATE SCHEMA below opens a transaction that Alembic's own
    # `begin_transaction()` then joins rather than owns. With `connect()` the whole migration
    # runs, reports success, and is rolled back on close — silently.
    async with engine.begin() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
