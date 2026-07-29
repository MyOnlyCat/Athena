from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret-that-is-long-enough",
        credential_key="4UlSOndzr4KYLmDMK5T5OmRsWLOtqzmNe01_sucGm2o=",
        bootstrap_username="admin",
        bootstrap_password="AdminPassw0rd!",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
