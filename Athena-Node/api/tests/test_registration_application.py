import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.services.master_client import MasterClient
from app.services.signing import sign_request


@pytest.mark.asyncio
async def test_node_submits_signed_registration_without_token() -> None:
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(202, json={"status": "pending"})

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://master.test",
    )
    client = MasterClient(
        "http://master.test",
        "018f47a2-4b5c-7def-8123-456789abcdef",
        "registration-secret-token-value-123",
        http,
    )
    payload: dict[str, Any] = {
        "node_id": "018f47a2-4b5c-7def-8123-456789abcdef",
        "reported_name": "上海接入节点",
        "hostname": "athena-node-01",
        "software_version": "0.1.0",
    }

    result = await client.submit_registration(payload)

    request = observed[0]
    assert result == {"status": "pending"}
    assert request.url.path == "/api/node/v1/registration-applications"
    assert json.loads(request.content) == payload
    assert b"registration-secret-token" not in request.content
    assert request.headers["X-Signature"] == sign_request(
        secret="registration-secret-token-value-123",
        method="POST",
        path_with_query="/api/node/v1/registration-applications",
        timestamp=request.headers["X-Timestamp"],
        nonce=request.headers["X-Nonce"],
        body=request.content,
    )


@pytest.mark.asyncio
async def test_node_preserves_master_registration_error_contract() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "code": "REGISTRATION_REJECTED",
                "message": "接入申请已被拒绝，请联系管理员恢复后手动重试",
            },
        )

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://master.test",
    )
    client = MasterClient(
        "http://master.test",
        "018f47a2-4b5c-7def-8123-456789abcdef",
        "registration-secret-token-value-123",
        http,
    )

    with pytest.raises(AppError) as captured:
        await client.submit_registration({"node_id": client.node_id})

    assert captured.value.code == "REGISTRATION_REJECTED"
    assert captured.value.message == "接入申请已被拒绝，请联系管理员恢复后手动重试"
    assert captured.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            503,
            json={
                "code": "DATABASE_DRIVER_ERROR",
                "message": "raw backend detail",
            },
        ),
        httpx.Response(503, text="service unavailable"),
    ],
)
async def test_node_normalizes_temporary_master_failures(
    response: httpx.Response,
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return response

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://master.test",
    )
    client = MasterClient(
        "http://master.test",
        "018f47a2-4b5c-7def-8123-456789abcdef",
        "registration-secret-token-value-123",
        http,
    )

    with pytest.raises(AppError) as captured:
        await client.submit_registration({"node_id": client.node_id})

    assert captured.value.code == "MASTER_TEMPORARILY_UNAVAILABLE"
    assert captured.value.message == "主节点暂时不可用，请稍后重试"
    assert captured.value.status_code == 503


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_registration_is_separate_from_connection_test_and_persists_pending_status(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted: list[dict[str, Any]] = []

    class FakeRegistrationClient:
        def __init__(self, base_url: str, node_id: str, token: str) -> None:
            assert base_url == "http://master.example.com:8001"
            assert len(node_id) == 36
            assert token == "registration-secret-token-value-123"

        async def submit_registration(self, payload: dict[str, Any]) -> dict[str, Any]:
            submitted.append(payload)
            return {"status": "pending"}

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.api.v1.master_settings.MasterClient",
        FakeRegistrationClient,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        headers = _auth_headers(client)
        runtime = app.state.master_runtime
        runtime.start_worker = False
        saved = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "http",
                "host": "master.example.com",
                "port": 8001,
                "token": "registration-secret-token-value-123",
            },
        )
        registered = client.post(
            "/api/v1/master-settings/registration",
            headers=headers,
        )
        loaded = client.get("/api/v1/master-settings", headers=headers)

    assert saved.status_code == 200
    assert registered.status_code == 202
    assert registered.json() == {"status": "pending"}
    assert loaded.json()["registration_status"] == "pending"
    assert submitted == [
        {
            "node_id": loaded.json()["node_id"],
            "reported_name": loaded.json()["node_name"],
            "hostname": submitted[0]["hostname"],
            "software_version": settings.node_version,
        }
    ]
    assert "token" not in json.dumps(submitted)


def test_pending_registration_refreshes_to_approved_from_master(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistrationClient:
        def __init__(self, base_url: str, node_id: str, token: str) -> None:
            assert base_url == "http://master.example.com:8001"
            assert len(node_id) == 36
            assert token == "registration-secret-token-value-123"

        async def submit_registration(self, payload: dict[str, Any]) -> dict[str, Any]:
            del payload
            return {"status": "pending"}

        async def get_registration_status(self) -> dict[str, Any]:
            return {"status": "approved"}

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.api.v1.master_settings.MasterClient",
        FakeRegistrationClient,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        headers = _auth_headers(client)
        app.state.master_runtime.start_worker = False
        saved = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "http",
                "host": "master.example.com",
                "port": 8001,
                "token": "registration-secret-token-value-123",
            },
        )
        submitted = client.post(
            "/api/v1/master-settings/registration",
            headers=headers,
        )
        synchronized = client.post(
            "/api/v1/master-settings/registration/status",
            headers=headers,
        )
        refreshed = client.get("/api/v1/master-settings", headers=headers)

    assert saved.status_code == 200
    assert submitted.status_code == 202
    assert synchronized.status_code == 200
    assert synchronized.json() == {"status": "approved"}
    assert refreshed.status_code == 200
    assert refreshed.json()["registration_status"] == "approved"


def test_pending_registration_refreshes_to_rejected_and_stops_pending_state(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_checks = 0

    class FakeRegistrationClient:
        def __init__(self, base_url: str, node_id: str, token: str) -> None:
            del base_url, node_id, token

        async def submit_registration(self, payload: dict[str, Any]) -> dict[str, Any]:
            del payload
            return {"status": "pending"}

        async def get_registration_status(self) -> dict[str, Any]:
            nonlocal status_checks
            status_checks += 1
            return {"status": "rejected"}

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.api.v1.master_settings.MasterClient",
        FakeRegistrationClient,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        headers = _auth_headers(client)
        app.state.master_runtime.start_worker = False
        client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "http",
                "host": "master.example.com",
                "port": 8001,
                "token": "registration-secret-token-value-123",
            },
        )
        client.post("/api/v1/master-settings/registration", headers=headers)
        synchronized = client.post(
            "/api/v1/master-settings/registration/status",
            headers=headers,
        )
        repeated = client.post(
            "/api/v1/master-settings/registration/status",
            headers=headers,
        )
        refreshed = client.get("/api/v1/master-settings", headers=headers)

    assert synchronized.json() == {"status": "rejected"}
    assert repeated.json() == {"status": "rejected"}
    assert status_checks == 1
    assert refreshed.json()["registration_status"] == "rejected"
