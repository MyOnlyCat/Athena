import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import create_engine


def runtime_settings(
    *,
    environment: str,
    database_url: str,
    data_dir: Path,
) -> dict[str, object]:
    values: dict[str, object] = {
        "environment": environment,
        "database_url": database_url,
        "jwt_secret": "test-jwt-secret-with-at-least-32-characters",
        "credential_key": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "data_dir": data_dir,
    }
    if environment == "production":
        values.update(
            bootstrap_username="admin",
            bootstrap_password="AdminPassword123",
        )
    return values


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_master_runtime_requires_an_explicit_database_url(
    environment: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="PostgreSQL 数据库地址"):
        Settings(**runtime_settings(environment=environment, database_url="", data_dir=tmp_path))


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_master_runtime_rejects_sqlite(
    environment: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match=r"postgresql\+asyncpg"):
        Settings(
            **runtime_settings(
                environment=environment,
                database_url="sqlite+aiosqlite:///./data/master.db",
                data_dir=tmp_path,
            )
        )


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_master_runtime_accepts_postgresql_asyncpg(
    environment: str,
    tmp_path: Path,
) -> None:
    settings = Settings(
        **runtime_settings(
            environment=environment,
            database_url="postgresql+asyncpg://athena:secret@db/athena",
            data_dir=tmp_path,
        )
    )

    assert settings.database_url == "postgresql+asyncpg://athena:secret@db/athena"


def test_database_schema_rejects_unsafe_identifier(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="database_schema"):
        Settings(
            **runtime_settings(
                environment="test",
                database_url="postgresql+asyncpg://athena:secret@db/athena",
                data_dir=tmp_path,
            ),
            database_schema='public; DROP SCHEMA public',
        )


def test_database_schema_defaults_to_public(tmp_path: Path) -> None:
    settings = Settings(
        **runtime_settings(
            environment="test",
            database_url="postgresql+asyncpg://athena:secret@db/athena",
            data_dir=tmp_path,
        )
    )

    assert settings.database_schema == "public"


def test_production_rejects_repository_placeholder_secrets(tmp_path: Path) -> None:
    values = runtime_settings(
        environment="production",
        database_url="postgresql+asyncpg://athena:secret@db/athena",
        data_dir=tmp_path,
    )
    values["jwt_secret"] = "replace-with-at-least-32-random-characters"

    with pytest.raises(ValueError, match="示例占位") as error:
        Settings(**values)

    assert str(values["jwt_secret"]) not in str(error.value)


def test_credential_key_must_be_a_valid_fernet_key(tmp_path: Path) -> None:
    values = runtime_settings(
        environment="test",
        database_url="postgresql+asyncpg://athena:secret@db/athena",
        data_dir=tmp_path,
    )
    values["credential_key"] = "x" * 44

    with pytest.raises(ValueError, match="Fernet") as error:
        Settings(**values)

    assert str(values["credential_key"]) not in str(error.value)


def test_settings_repr_hides_database_and_application_secrets(tmp_path: Path) -> None:
    values = runtime_settings(
        environment="production",
        database_url="postgresql+asyncpg://athena:database-secret@db/athena",
        data_dir=tmp_path,
    )
    settings = Settings(**values)
    rendered = repr(settings)

    assert "database-secret" not in rendered
    assert str(values["jwt_secret"]) not in rendered
    assert str(values["credential_key"]) not in rendered
    assert str(values["bootstrap_password"]) not in rendered


@pytest.mark.asyncio
async def test_database_connections_apply_bounded_postgresql_timeouts(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=os.environ["ATHENA_TEST_POSTGRES_URL"],
        jwt_secret="test-jwt-secret-with-at-least-32-characters",
        credential_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        data_dir=tmp_path,
    )
    engine = create_engine(settings)

    try:
        async with engine.connect() as connection:
            current_schema = await connection.scalar(text("SELECT current_schema()"))
            search_path = await connection.scalar(text("SHOW search_path"))
            statement_timeout = await connection.scalar(
                text(
                    "SELECT (EXTRACT(EPOCH FROM "
                    "current_setting('statement_timeout')::interval) * 1000)::integer"
                )
            )
            idle_transaction_timeout = await connection.scalar(
                text(
                    "SELECT (EXTRACT(EPOCH FROM "
                    "current_setting('idle_in_transaction_session_timeout')::interval) "
                    "* 1000)::integer"
                )
            )
            lock_timeout = await connection.scalar(
                text(
                    "SELECT (EXTRACT(EPOCH FROM "
                    "current_setting('lock_timeout')::interval) * 1000)::integer"
                )
            )

        assert current_schema == "public"
        assert search_path == "public"
        assert statement_timeout == 30_000
        assert idle_transaction_timeout == 60_000
        assert lock_timeout == 10_000
        assert engine.sync_engine.pool.size() == 10
    finally:
        await engine.dispose()
