import argparse
import asyncio
import os
import re
from collections.abc import Sequence
from typing import Literal, cast

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.postgres import is_safe_postgres_schema_name, postgres_server_settings

SchemaOperation = Literal["ensure", "create-smoke", "drop-smoke"]
_SCHEMA_OPERATIONS: tuple[SchemaOperation, ...] = (
    "ensure",
    "create-smoke",
    "drop-smoke",
)
_SMOKE_SCHEMA = re.compile(r"athena_smoke_[0-9a-f]{32}")


def _validate_operation(operation: SchemaOperation, schema: str) -> None:
    if not is_safe_postgres_schema_name(schema):
        raise ValueError("schema must be a safe PostgreSQL identifier")
    if operation != "ensure" and _SMOKE_SCHEMA.fullmatch(schema) is None:
        raise ValueError("smoke schema operations require an isolated athena_smoke schema")


async def _lock_schema(connection: AsyncConnection, schema: str) -> None:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": f"athena-schema:{schema}"},
    )


async def apply_schema_operation(
    *,
    database_url: str,
    operation: SchemaOperation,
    schema: str,
) -> None:
    _validate_operation(operation, schema)
    if make_url(database_url).drivername != "postgresql+asyncpg":
        raise ValueError("schema operations require postgresql+asyncpg")

    engine = create_async_engine(
        database_url,
        hide_parameters=True,
        connect_args={"server_settings": postgres_server_settings(schema="public")},
    )
    try:
        async with engine.begin() as connection:
            await _lock_schema(connection, schema)
            quoted_schema = connection.dialect.identifier_preparer.quote(schema)
            if operation == "ensure":
                exists = await connection.scalar(
                    text("SELECT 1 FROM pg_namespace WHERE nspname = :schema"),
                    {"schema": schema},
                )
                if exists is None:
                    await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            elif operation == "create-smoke":
                await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            else:
                await connection.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
    finally:
        await engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare an Athena Master development or smoke-test PostgreSQL schema."
    )
    parser.add_argument("operation", choices=_SCHEMA_OPERATIONS)
    parser.add_argument("schema")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    database_url = os.environ.get("ATHENA_MASTER_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("ATHENA_MASTER_DATABASE_URL is required")
    asyncio.run(
        apply_schema_operation(
            database_url=database_url,
            operation=cast(SchemaOperation, arguments.operation),
            schema=arguments.schema,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
