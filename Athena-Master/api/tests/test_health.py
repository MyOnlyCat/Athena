from httpx import AsyncClient


async def test_health_checks_application_and_database(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "athena-master-api",
        "database": "ok",
    }
