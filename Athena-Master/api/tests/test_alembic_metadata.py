import asyncio
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import JSON, Column, String

from alembic import command
from app.core.database import Base
from app.core.schema_defaults import compare_server_default
from app.models import asset, audit, registration, user  # noqa: F401
from tests.postgres import (
    PostgresTestSchema,
    alembic_config,
    require_test_postgres_url,
)


def test_test_postgres_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATHENA_TEST_POSTGRES_URL", raising=False)

    with pytest.raises(pytest.UsageError, match="ATHENA_TEST_POSTGRES_URL"):
        require_test_postgres_url()


def test_test_postgres_url_rejects_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ATHENA_TEST_POSTGRES_URL",
        "sqlite+aiosqlite:///./data/athena-master.db",
    )

    with pytest.raises(pytest.UsageError, match=r"postgresql\+asyncpg"):
        require_test_postgres_url()


def test_test_postgres_url_comes_from_the_dedicated_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "postgresql+asyncpg://athena_test:secret@127.0.0.1:55432/athena_test"
    monkeypatch.setenv("ATHENA_TEST_POSTGRES_URL", expected)
    monkeypatch.setenv(
        "ATHENA_MASTER_DATABASE_URL",
        "postgresql+asyncpg://wrong:wrong@127.0.0.1:5432/wrong",
    )

    assert require_test_postgres_url() == expected


def test_postgres_schema_repr_does_not_expose_database_credentials(tmp_path: Path) -> None:
    secret_url = "postgresql+asyncpg://athena:do-not-log@database/athena"
    schema = PostgresTestSchema(
        database_url=secret_url,
        name="athena_test_00000000000000000000000000000000",
        api_root=tmp_path,
        public_objects_before=frozenset(),
    )

    assert secret_url not in repr(schema)
    assert "do-not-log" not in repr(schema)


def test_json_server_defaults_are_compared_as_canonical_json_text() -> None:
    inspected_column = Column("management_tags", JSON(), server_default="[]")
    metadata_column = Column("management_tags", JSON(), server_default="[]")

    assert (
        compare_server_default(
            object(),
            inspected_column,
            metadata_column,
            "'[]'::json",
            metadata_column.server_default,
            "'[]'",
        )
        is False
    )
    assert (
        compare_server_default(
            object(),
            inspected_column,
            metadata_column,
            "'{\"scope\": [\"node\", \"host\"]}'::jsonb",
            metadata_column.server_default,
            "'{\"scope\":[\"node\"]}'",
        )
        is True
    )


def test_non_json_server_defaults_use_the_dialect_comparison() -> None:
    inspected_column = Column("status", String(20), server_default="active")
    metadata_column = Column("status", String(20), server_default="active")

    assert (
        compare_server_default(
            object(),
            inspected_column,
            metadata_column,
            "'active'::character varying",
            metadata_column.server_default,
            "'active'",
        )
        is None
    )


def test_alembic_revision_graph_has_one_expected_head() -> None:
    scripts = ScriptDirectory.from_config(
        alembic_config(Path(__file__).resolve().parents[1])
    )

    assert scripts.get_heads() == ["0008_operation_audit"]


def test_alembic_upgrade_requires_an_explicit_master_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ATHENA_MASTER_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="ATHENA_MASTER_DATABASE_URL"):
        command.upgrade(
            alembic_config(Path(__file__).resolve().parents[1]),
            "head",
            sql=True,
        )


def test_alembic_rejects_an_unsafe_database_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "ATHENA_MASTER_DATABASE_URL",
        "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/invalid",
    )
    monkeypatch.setenv("ATHENA_MASTER_DATABASE_SCHEMA", "public, pg_catalog")

    with pytest.raises(RuntimeError, match="ATHENA_MASTER_DATABASE_SCHEMA"):
        command.upgrade(
            alembic_config(Path(__file__).resolve().parents[1]),
            "head",
        )


def test_alembic_cli_migrates_only_the_configured_schema(
    postgres_schema: PostgresTestSchema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATHENA_MASTER_DATABASE_URL", postgres_schema.database_url)
    monkeypatch.setenv("ATHENA_MASTER_DATABASE_SCHEMA", postgres_schema.name)

    command.upgrade(
        alembic_config(Path(__file__).resolve().parents[1]),
        "head",
    )

    assert asyncio.run(postgres_schema.table_names()) == {
        "access_nodes",
        "alembic_version",
        "audit_logs",
        "host_assets",
        "node_nonces",
        "registration_applications",
        "revoked_tokens",
        "users",
    }
    assert asyncio.run(postgres_schema.public_schema_is_unchanged())


@pytest.mark.asyncio
async def test_alembic_upgrade_matches_model_metadata(
    migrated_postgres_schema: PostgresTestSchema,
) -> None:
    assert migrated_postgres_schema.name != "public"
    assert await migrated_postgres_schema.table_names() == {
        "access_nodes",
        "alembic_version",
        "audit_logs",
        "host_assets",
        "node_nonces",
        "registration_applications",
        "revoked_tokens",
        "users",
    }
    assert await migrated_postgres_schema.compare_metadata(Base.metadata) == []
    assert await migrated_postgres_schema.public_schema_is_unchanged()
