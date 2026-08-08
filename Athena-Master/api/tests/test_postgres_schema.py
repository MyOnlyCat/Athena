import pytest

from app.cli.postgres_schema import SchemaOperation, apply_schema_operation


@pytest.mark.parametrize("operation", ["create-smoke", "drop-smoke"])
async def test_smoke_schema_operations_reject_non_smoke_schema(
    operation: SchemaOperation,
) -> None:
    with pytest.raises(ValueError, match="isolated athena_smoke schema"):
        await apply_schema_operation(
            database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
            operation=operation,
            schema="public",
        )


async def test_schema_operation_rejects_unsafe_identifier_before_connecting() -> None:
    with pytest.raises(ValueError, match="safe PostgreSQL identifier"):
        await apply_schema_operation(
            database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
            operation="ensure",
            schema="athena-dev",
        )


async def test_schema_operation_rejects_non_postgresql_driver_before_connecting() -> None:
    with pytest.raises(ValueError, match=r"postgresql\+asyncpg"):
        await apply_schema_operation(
            database_url="sqlite+aiosqlite:///unused.db",
            operation="ensure",
            schema="athena_dev",
        )
