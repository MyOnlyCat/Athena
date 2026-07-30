from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def read_identity(settings: Settings) -> dict[str, object]:
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/v1/master-settings",
            headers=auth_headers(client),
        )
    assert response.status_code == 200
    return response.json()


def test_generated_node_identity_survives_restart(settings: Settings) -> None:
    first = read_identity(settings)
    second = read_identity(
        settings.model_copy(update={"node_name": "Changed environment name"})
    )

    parsed = UUID(str(first["node_id"]))
    assert parsed.version == 7
    assert second["node_id"] == first["node_id"]
    assert first["node_name"] == "Athena Node"
    assert second["node_name"] == "Athena Node"


def test_test_environment_can_inject_fixed_node_identity(settings: Settings) -> None:
    fixed_id = "018f47a2-4b5c-7def-8123-456789abcdef"

    identity = read_identity(settings.model_copy(update={"node_id": fixed_id}))

    assert identity["node_id"] == fixed_id


def test_test_environment_rejects_non_uuid7_identity(settings: Settings) -> None:
    invalid = settings.model_copy(update={"node_id": "legacy-environment-node-id"})

    with pytest.raises(ValueError, match="UUIDv7"):
        read_identity(invalid)


def test_production_ignores_legacy_configured_node_id_across_restarts(
    settings: Settings,
) -> None:
    first = read_identity(settings.model_copy(
        update={
            "environment": "production",
            "node_id": "first-legacy-environment-node-id",
        }
    ))
    second = read_identity(settings.model_copy(
        update={
            "environment": "production",
            "node_id": "changed-legacy-environment-node-id",
        }
    ))

    assert first["node_id"] == second["node_id"]
    assert first["node_id"] != "first-legacy-environment-node-id"
    assert second["node_id"] != "changed-legacy-environment-node-id"
    assert UUID(str(first["node_id"])).version == 7
