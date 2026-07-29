import asyncio
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.services.crypto import CredentialCipher
from app.services.master_client import MasterClient
from app.services.signing import sign_request


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class FakeMasterRuntime:
    def __init__(self) -> None:
        self.status = "running"
        self.tested: list[Any] = []
        self.applied: list[Any] = []
        self.test_error: AppError | None = None

    async def test(self, config: Any) -> None:
        self.tested.append(config)
        if self.test_error is not None:
            raise self.test_error

    async def apply(self, config: Any) -> None:
        self.applied.append(config)


def configured_client(
    settings: Settings,
    **updates: Any,
) -> Iterator[tuple[TestClient, FakeMasterRuntime]]:
    app = create_app(settings.model_copy(update=updates))
    with TestClient(app) as client:
        runtime = FakeMasterRuntime()
        app.state.master_runtime = runtime
        yield client, runtime


def database_path(settings: Settings) -> Path:
    return Path(settings.database_url.removeprefix("sqlite+aiosqlite:///"))


def stored_ciphertext(settings: Settings) -> str:
    with sqlite3.connect(database_path(settings)) as connection:
        row = connection.execute(
            "SELECT encrypted_token FROM master_settings WHERE id = 1"
        ).fetchone()
    assert row is not None
    return str(row[0])


def stored_address(settings: Settings) -> tuple[str, str, int]:
    with sqlite3.connect(database_path(settings)) as connection:
        row = connection.execute(
            "SELECT scheme, host, port FROM master_settings WHERE id = 1"
        ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1]), int(row[2])


def test_get_uses_environment_defaults_and_redacts_token(settings: Settings) -> None:
    clients = configured_client(
        settings,
        master_node_url="https://master.example.com:9443",
        node_token="environment-secret",
    )
    client, _ = next(clients)
    try:
        response = client.get("/api/v1/master-settings", headers=auth_headers(client))
    finally:
        clients.close()

    assert response.status_code == 200
    assert response.json() == {
        "scheme": "https",
        "host": "master.example.com",
        "port": 9443,
        "has_token": True,
        "runtime_status": "running",
    }
    assert "environment-secret" not in response.text
    assert "token" not in response.text.replace("has_token", "")


def test_put_encrypts_token_and_never_returns_it(settings: Settings) -> None:
    clients = configured_client(settings)
    client, runtime = next(clients)
    try:
        response = client.put(
            "/api/v1/master-settings",
            headers=auth_headers(client),
            json={
                "scheme": "https",
                "host": "master.example.com",
                "port": 9443,
                "token": "new-master-secret",
            },
        )
        ciphertext = stored_ciphertext(settings)
    finally:
        clients.close()

    assert response.status_code == 200
    assert response.json()["has_token"] is True
    assert "new-master-secret" not in response.text
    assert ciphertext != "new-master-secret"
    assert CredentialCipher(settings.credential_key).decrypt(ciphertext) == "new-master-secret"
    assert runtime.tested[0].base_url == "https://master.example.com:9443"
    assert runtime.applied[0].base_url == "https://master.example.com:9443"


def test_put_with_empty_token_retains_existing_ciphertext(settings: Settings) -> None:
    clients = configured_client(settings)
    client, runtime = next(clients)
    headers = auth_headers(client)
    try:
        first = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "https",
                "host": "old-master.example.com",
                "port": 443,
                "token": "saved-secret",
            },
        )
        first_ciphertext = stored_ciphertext(settings)
        second = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "http",
                "host": "new-master.example.com",
                "port": 8080,
                "token": "",
            },
        )
        second_ciphertext = stored_ciphertext(settings)
    finally:
        clients.close()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first_ciphertext == second_ciphertext
    assert runtime.tested[-1].token == "saved-secret"
    assert runtime.applied[-1].base_url == "http://new-master.example.com:8080"


def test_saved_database_settings_override_environment_after_restart(
    settings: Settings,
) -> None:
    initial_clients = configured_client(
        settings,
        master_node_url="https://environment.example.com:9443",
        node_token="environment-secret",
    )
    initial_client, _ = next(initial_clients)
    try:
        saved = initial_client.put(
            "/api/v1/master-settings",
            headers=auth_headers(initial_client),
            json={
                "scheme": "http",
                "host": "database.example.com",
                "port": 8080,
                "token": "database-secret",
            },
        )
    finally:
        initial_clients.close()

    restarted_app = create_app(
        settings.model_copy(
            update={
                "master_node_url": "https://changed-environment.example.com:443",
                "node_token": "changed-environment-secret",
            }
        )
    )
    with TestClient(restarted_app) as restarted_client:
        runtime = FakeMasterRuntime()
        restarted_app.state.master_runtime = runtime
        headers = auth_headers(restarted_client)
        loaded = restarted_client.get("/api/v1/master-settings", headers=headers)
        tested = restarted_client.post(
            "/api/v1/master-settings/test",
            headers=headers,
            json={
                "scheme": "https",
                "host": "candidate.example.com",
                "port": 443,
                "token": "",
            },
        )

    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json()["host"] == "database.example.com"
    assert loaded.json()["port"] == 8080
    assert tested.status_code == 200
    assert runtime.tested[0].token == "database-secret"


def test_invalid_master_host_and_port_return_422_without_testing(
    settings: Settings,
) -> None:
    clients = configured_client(settings)
    client, runtime = next(clients)
    headers = auth_headers(client)
    try:
        invalid_host = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={"scheme": "https", "host": "not a host", "port": 443, "token": "secret"},
        )
        invalid_port = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "https",
                "host": "master.example.com",
                "port": 65_536,
                "token": "secret",
            },
        )
    finally:
        clients.close()

    assert invalid_host.status_code == 422
    assert invalid_port.status_code == 422
    assert runtime.tested == []
    assert runtime.applied == []


def test_failed_connection_test_keeps_database_and_runtime_unchanged(
    settings: Settings,
) -> None:
    clients = configured_client(settings)
    client, runtime = next(clients)
    headers = auth_headers(client)
    try:
        saved = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "https",
                "host": "old-master.example.com",
                "port": 443,
                "token": "saved-secret",
            },
        )
        old_ciphertext = stored_ciphertext(settings)
        runtime.test_error = AppError(
            "MASTER_CONNECTION_FAILED",
            "Unable to connect to the master node",
        )

        failed = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "http",
                "host": "new-master.example.com",
                "port": 8080,
                "token": "must-not-leak",
            },
        )
        current_ciphertext = stored_ciphertext(settings)
        current_address = stored_address(settings)
    finally:
        clients.close()

    assert saved.status_code == 200
    assert failed.status_code == 400
    assert failed.json()["code"] == "MASTER_CONNECTION_FAILED"
    assert "must-not-leak" not in failed.text
    assert current_ciphertext == old_ciphertext
    assert current_address == ("https", "old-master.example.com", 443)
    assert len(runtime.applied) == 1


def test_connection_test_with_empty_token_uses_saved_token_without_applying(
    settings: Settings,
) -> None:
    clients = configured_client(settings)
    client, runtime = next(clients)
    headers = auth_headers(client)
    try:
        saved = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "https",
                "host": "master.example.com",
                "port": 443,
                "token": "saved-secret",
            },
        )
        apply_count = len(runtime.applied)
        tested = client.post(
            "/api/v1/master-settings/test",
            headers=headers,
            json={
                "scheme": "https",
                "host": "candidate.example.com",
                "port": 9443,
                "token": "",
            },
        )
    finally:
        clients.close()

    assert saved.status_code == 200
    assert tested.status_code == 200
    assert tested.json() == {"status": "success"}
    assert runtime.tested[-1].token == "saved-secret"
    assert len(runtime.applied) == apply_count


@pytest.mark.asyncio
async def test_master_client_connection_test_is_signed() -> None:
    observed: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        expected = sign_request(
            secret="node-secret",
            method=request.method,
            path_with_query=request.url.raw_path.decode(),
            timestamp=request.headers["X-Timestamp"],
            nonce=request.headers["X-Nonce"],
            body=request.content,
        )
        assert request.headers["X-Node-Id"] == "node-1"
        assert request.headers["X-Signature"] == expected
        return httpx.Response(200, json={"accepted_at": "2026-07-30T12:00:00Z"})

    async with httpx.AsyncClient(
        base_url="https://master.example.com:9443",
        transport=httpx.MockTransport(handle),
    ) as http_client:
        master = MasterClient(
            "https://master.example.com:9443",
            "node-1",
            "node-secret",
            http_client,
        )
        result = await master.test_connection()

    assert result == {"accepted_at": "2026-07-30T12:00:00Z"}
    assert len(observed) == 1
    assert observed[0].url.path == "/api/node/v1/nodes/heartbeat"


class RuntimeTracker:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.active_workers = 0
        self.maximum_workers = 0
        self.fail_recovery = False


class FakeRuntimeClient:
    def __init__(self, token: str, tracker: RuntimeTracker) -> None:
        self.token = token
        self.tracker = tracker

    async def close(self) -> None:
        self.tracker.events.append(f"client-close:{self.token}")


class FakeInventory:
    def __init__(self, client: FakeRuntimeClient, tracker: RuntimeTracker) -> None:
        self.client = client
        self.tracker = tracker

    def notify_change(self) -> None:
        self.tracker.events.append(f"notify:{self.client.token}")

    async def run(self, stop: asyncio.Event, claim_callback: Any = None) -> None:
        self.tracker.events.append(f"worker-start:{self.client.token}")
        self.tracker.active_workers += 1
        self.tracker.maximum_workers = max(
            self.tracker.maximum_workers,
            self.tracker.active_workers,
        )
        try:
            await stop.wait()
        finally:
            self.tracker.active_workers -= 1
            self.tracker.events.append(f"worker-stop:{self.client.token}")


class FakeExecutor:
    def __init__(self, client: FakeRuntimeClient, tracker: RuntimeTracker) -> None:
        self.client = client
        self.tracker = tracker

    async def recover(self) -> int:
        self.tracker.events.append(f"recover:{self.client.token}")
        if self.tracker.fail_recovery:
            raise RuntimeError("recovery failed")
        return 0

    async def poll(self) -> None:
        return None

    async def close(self) -> None:
        self.tracker.events.append(f"executor-close:{self.client.token}")


def runtime_with_fakes(settings: Settings, tracker: RuntimeTracker) -> Any:
    from app.services.master_runtime import MasterRuntime

    def client_factory(
        base_url: str,
        node_id: str,
        token: str,
    ) -> FakeRuntimeClient:
        del base_url, node_id
        return FakeRuntimeClient(token, tracker)

    def inventory_factory(
        active_settings: Settings,
        session_factory: Any,
        client: FakeRuntimeClient,
    ) -> FakeInventory:
        del active_settings, session_factory
        return FakeInventory(client, tracker)

    def executor_factory(**kwargs: Any) -> FakeExecutor:
        return FakeExecutor(kwargs["master_client"], tracker)

    return MasterRuntime(
        settings=settings,
        session_factory=object(),
        artifact_service=object(),
        gateway=object(),
        cipher=CredentialCipher(settings.credential_key),
        client_factory=client_factory,
        inventory_factory=inventory_factory,
        executor_factory=executor_factory,
        start_worker=True,
    )


@pytest.mark.asyncio
async def test_runtime_replacement_stops_old_resources_before_one_new_loop(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    runtime = runtime_with_fakes(settings, tracker)

    await runtime.apply(MasterConfig("https", "old.example.com", 443, "old"))
    await asyncio.sleep(0)
    await runtime.apply(MasterConfig("https", "new.example.com", 443, "new"))
    await asyncio.sleep(0)

    assert tracker.events.index("worker-stop:old") < tracker.events.index("client-close:old")
    assert tracker.events.index("client-close:old") < tracker.events.index("worker-start:new")
    assert tracker.active_workers == 1
    assert tracker.maximum_workers == 1
    assert runtime.status == "running"

    await runtime.stop()

    assert tracker.active_workers == 0
    assert tracker.events[-2:] == ["executor-close:new", "client-close:new"]
    assert runtime.status == "stopped"


@pytest.mark.asyncio
async def test_concurrent_runtime_replacements_are_serialized_by_one_worker(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    runtime = runtime_with_fakes(settings, tracker)
    await runtime.apply(MasterConfig("https", "first.example.com", 443, "first"))
    await asyncio.sleep(0)

    await asyncio.gather(
        runtime.apply(MasterConfig("https", "second.example.com", 443, "second")),
        runtime.apply(MasterConfig("https", "third.example.com", 443, "third")),
    )
    await asyncio.sleep(0)

    assert tracker.active_workers == 1
    assert tracker.maximum_workers == 1
    assert sum(event.startswith("worker-start:") for event in tracker.events) == 3

    await runtime.stop()


@pytest.mark.asyncio
async def test_failed_runtime_start_closes_new_resources_once(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    tracker.fail_recovery = True
    runtime = runtime_with_fakes(settings, tracker)

    with pytest.raises(RuntimeError, match="recovery failed"):
        await runtime.apply(MasterConfig("https", "master.example.com", 443, "secret"))

    assert tracker.events.count("executor-close:secret") == 1
    assert tracker.events.count("client-close:secret") == 1
    assert runtime.status == "stopped"


def test_lifespan_cleans_runtime_when_startup_apply_fails(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.master_runtime import MasterRuntime

    stopped: list[bool] = []

    async def fail_apply(runtime: MasterRuntime, config: Any) -> None:
        del runtime, config
        raise RuntimeError("startup apply failed")

    async def record_stop(runtime: MasterRuntime) -> None:
        del runtime
        stopped.append(True)

    monkeypatch.setattr(MasterRuntime, "apply", fail_apply)
    monkeypatch.setattr(MasterRuntime, "stop", record_stop)

    with pytest.raises(RuntimeError, match="startup apply failed"):
        with TestClient(create_app(settings)):
            pass

    assert stopped == [True]
