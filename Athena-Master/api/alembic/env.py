import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.database import Base
from app.core.postgres import (
    DEFAULT_IDLE_TRANSACTION_TIMEOUT_MS,
    DEFAULT_LOCK_TIMEOUT_MS,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    is_safe_postgres_schema_name,
    postgres_server_settings,
)
from app.core.schema_defaults import compare_server_default
from app.models import asset, audit, registration, user  # noqa: F401


def _positive_environment_integer(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value

config = context.config
configured_connection = config.attributes.get("connection")
database_url = os.getenv("ATHENA_MASTER_DATABASE_URL")
database_schema = os.getenv("ATHENA_MASTER_DATABASE_SCHEMA") or "public"
server_settings = postgres_server_settings(
    schema=database_schema,
    statement_timeout_ms=_positive_environment_integer(
        "ATHENA_MASTER_DATABASE_STATEMENT_TIMEOUT_MS",
        DEFAULT_STATEMENT_TIMEOUT_MS,
    ),
    idle_transaction_timeout_ms=_positive_environment_integer(
        "ATHENA_MASTER_DATABASE_IDLE_TRANSACTION_TIMEOUT_MS",
        DEFAULT_IDLE_TRANSACTION_TIMEOUT_MS,
    ),
    lock_timeout_ms=_positive_environment_integer(
        "ATHENA_MASTER_DATABASE_LOCK_TIMEOUT_MS",
        DEFAULT_LOCK_TIMEOUT_MS,
    ),
)
if not is_safe_postgres_schema_name(database_schema):
    raise RuntimeError(
        "ATHENA_MASTER_DATABASE_SCHEMA must be a safe PostgreSQL identifier"
    )
if configured_connection is None:
    if not database_url:
        raise RuntimeError(
            "ATHENA_MASTER_DATABASE_URL is required when running Master Alembic migrations"
        )
    if make_url(database_url).drivername != "postgresql+asyncpg":
        raise RuntimeError("Master Alembic migrations require postgresql+asyncpg")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        compare_server_default=compare_server_default,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Master Alembic migrations require PostgreSQL")
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_server_default=compare_server_default,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"server_settings": server_settings},
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    if configured_connection is not None:
        run_migrations(configured_connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
