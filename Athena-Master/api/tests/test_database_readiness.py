from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.main import create_app
from tests.postgres import PostgresTestSchema


def settings_for_schema(schema: PostgresTestSchema, data_dir: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=schema.database_url,
        database_schema=schema.name,
        jwt_secret="test-jwt-secret-with-at-least-32-characters",
        credential_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        data_dir=data_dir,
    )


@pytest.mark.asyncio
async def test_master_refuses_to_start_before_alembic_head(
    postgres_schema: PostgresTestSchema,
    tmp_path: Path,
) -> None:
    app = create_app(settings_for_schema(postgres_schema, tmp_path))

    with pytest.raises(RuntimeError, match="Alembic head"):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.asyncio
async def test_master_starts_when_database_is_at_alembic_head(
    migrated_postgres_schema: PostgresTestSchema,
    tmp_path: Path,
) -> None:
    app = create_app(settings_for_schema(migrated_postgres_schema, tmp_path))

    async with app.router.lifespan_context(app):
        async with app.state.db_engine.connect() as connection:
            current_schema = await connection.scalar(text("SELECT current_schema()"))

    assert current_schema == migrated_postgres_schema.name
