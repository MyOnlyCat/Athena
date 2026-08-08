from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.schema_defaults import compare_server_default

TEST_POSTGRES_ENV = "ATHENA_TEST_POSTGRES_URL"
POSTGRES_DRIVER = "postgresql+asyncpg"
_TEST_SCHEMA_PATTERN = re.compile(r"athena_test_[0-9a-f]{32}")


def require_test_postgres_url() -> str:
    database_url = os.environ.get(TEST_POSTGRES_ENV, "").strip()
    if not database_url:
        raise pytest.UsageError(
            f"{TEST_POSTGRES_ENV} is required; Master tests never fall back to SQLite"
        )
    try:
        driver_name = make_url(database_url).drivername
    except (TypeError, ValueError) as error:
        raise pytest.UsageError(f"{TEST_POSTGRES_ENV} is not a valid database URL") from error
    if driver_name != POSTGRES_DRIVER:
        raise pytest.UsageError(f"{TEST_POSTGRES_ENV} must use {POSTGRES_DRIVER}")
    return database_url


def alembic_config(api_root: Path, database_url: str | None = None) -> Config:
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _quoted_test_schema(schema_name: str) -> str:
    if _TEST_SCHEMA_PATTERN.fullmatch(schema_name) is None:
        raise ValueError("refusing to operate on a non-test PostgreSQL schema")
    return f'"{schema_name}"'


def _schema_engine(database_url: str, schema_name: str) -> AsyncEngine:
    _quoted_test_schema(schema_name)
    return create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema_name}},
    )


def _table_names(connection: Connection, schema: str | None = None) -> set[str]:
    return set(inspect(connection).get_table_names(schema=schema))


def _schema_objects(connection: Connection, schema: str) -> frozenset[str]:
    rows = connection.execute(
        text(
            "SELECT 'relation:' || c.relkind::text || ':' || c.relname AS identity "
            "FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema "
            "UNION ALL "
            "SELECT 'function:' || p.proname || '(' || "
            "pg_catalog.pg_get_function_identity_arguments(p.oid) || ')' "
            "FROM pg_catalog.pg_proc AS p "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
            "WHERE n.nspname = :schema "
            "UNION ALL "
            "SELECT 'type:' || t.typtype::text || ':' || t.typname "
            "FROM pg_catalog.pg_type AS t "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = t.typnamespace "
            "WHERE n.nspname = :schema"
        ),
        {"schema": schema},
    )
    return frozenset(str(identity) for identity in rows.scalars())


def _metadata_drift(connection: Connection, metadata: MetaData) -> list[object]:
    migration_context = MigrationContext.configure(
        connection,
        opts={
            "compare_server_default": compare_server_default,
            "compare_type": True,
        },
    )
    return list(compare_metadata(migration_context, metadata))


def _upgrade_to_head(connection: Connection, api_root: Path, database_url: str) -> None:
    config = alembic_config(api_root, database_url)
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


@dataclass(frozen=True)
class PostgresTestSchema:
    database_url: str = field(repr=False)
    name: str
    api_root: Path
    public_objects_before: frozenset[str]

    def create_engine(self) -> AsyncEngine:
        return _schema_engine(self.database_url, self.name)

    async def upgrade_to_head(self) -> None:
        engine = self.create_engine()
        try:
            async with engine.begin() as connection:
                await connection.run_sync(
                    _upgrade_to_head,
                    self.api_root,
                    self.database_url,
                )
        finally:
            await engine.dispose()

    async def table_names(self) -> set[str]:
        engine = self.create_engine()
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_table_names)
        finally:
            await engine.dispose()

    async def compare_metadata(self, metadata: MetaData) -> list[object]:
        engine = self.create_engine()
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_metadata_drift, metadata)
        finally:
            await engine.dispose()

    async def public_schema_is_unchanged(self) -> bool:
        engine = create_async_engine(self.database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                current = await connection.run_sync(_schema_objects, "public")
        finally:
            await engine.dispose()
        return current == self.public_objects_before


@pytest.fixture(scope="session")
def test_postgres_url() -> str:
    return require_test_postgres_url()


async def _create_test_schema(database_url: str, schema_name: str) -> frozenset[str]:
    quoted_schema = _quoted_test_schema(schema_name)
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            public_objects = await connection.run_sync(_schema_objects, "public")
            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
    finally:
        await engine.dispose()
    return public_objects


async def _drop_test_schema(
    database_url: str,
    schema_name: str,
    public_objects_before: frozenset[str],
) -> bool:
    quoted_schema = _quoted_test_schema(schema_name)
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            public_objects = await connection.run_sync(_schema_objects, "public")
            await connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE"))
    finally:
        await engine.dispose()
    return public_objects == public_objects_before


@pytest.fixture
def postgres_schema(test_postgres_url: str) -> Iterator[PostgresTestSchema]:
    api_root = Path(__file__).resolve().parents[1]
    schema_name = f"athena_test_{uuid4().hex}"
    public_objects_before = asyncio.run(_create_test_schema(test_postgres_url, schema_name))
    schema = PostgresTestSchema(
        database_url=test_postgres_url,
        name=schema_name,
        api_root=api_root,
        public_objects_before=public_objects_before,
    )
    try:
        yield schema
    finally:
        public_schema_unchanged = asyncio.run(
            _drop_test_schema(
                test_postgres_url,
                schema_name,
                public_objects_before,
            )
        )
        if not public_schema_unchanged:
            pytest.fail("PostgreSQL test changed tables in the public schema")


@pytest.fixture
def migrated_postgres_schema(
    postgres_schema: PostgresTestSchema,
) -> PostgresTestSchema:
    asyncio.run(postgres_schema.upgrade_to_head())
    return postgres_schema
