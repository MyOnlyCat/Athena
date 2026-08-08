from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

if TYPE_CHECKING:
    from tests.postgres import PostgresTestSchema

pytest_plugins = ("tests.postgres",)


@pytest.fixture
def settings(tmp_path: Path, migrated_postgres_schema: PostgresTestSchema) -> Settings:
    return Settings(
        environment="test",
        database_url=migrated_postgres_schema.database_url,
        database_schema=migrated_postgres_schema.name,
        jwt_secret="test-jwt-secret-with-at-least-32-characters",
        credential_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        bootstrap_username="admin",
        bootstrap_password="AdminPassword123",
        data_dir=tmp_path,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as test_client:
            yield test_client
