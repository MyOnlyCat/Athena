from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError


async def test_health_checks_application_and_database(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "athena-master-api",
        "database": "ok",
    }


@pytest.mark.asyncio
async def test_database_unavailability_uses_stable_temporary_error_contract(
    client: AsyncClient,
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    @asynccontextmanager
    async def unavailable_session() -> AsyncIterator[None]:
        raise OperationalError("SELECT 1", {}, OSError("database unavailable"))
        yield

    app.state.session_factory = unavailable_session

    response = await client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "code": "MASTER_TEMPORARILY_UNAVAILABLE",
        "message": "主节点暂时不可用，请稍后重试",
    }
    assert "Master database operation failed" in caplog.text
    assert "database unavailable" in caplog.text
