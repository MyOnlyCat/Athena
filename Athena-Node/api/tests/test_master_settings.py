import asyncio
import sqlite3
import threading
from collections.abc import Iterator
from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
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
        self.status = "online"
        self.tested: list[Any] = []
        self.applied: list[Any] = []
        self.test_error: AppError | None = None
        self.prepare_error: Exception | None = None
        self.test_delay = 0.0
        self.discarded: list[Any] = []
        self.reconfiguring = 0
        self.maximum_reconfiguring = 0
        self._reconfigure_lock = asyncio.Lock()

    @asynccontextmanager
    async def reconfigure(self):
        async with self._reconfigure_lock:
            self.reconfiguring += 1
            self.maximum_reconfiguring = max(
                self.maximum_reconfiguring,
                self.reconfiguring,
            )
            try:
                yield
            finally:
                self.reconfiguring -= 1

    async def test(self, config: Any) -> None:
        self.tested.append(config)
        if self.test_delay:
            await asyncio.sleep(self.test_delay)
        if self.test_error is not None:
            raise self.test_error

    async def prepare(self, config: Any) -> Any:
        if self.prepare_error is not None:
            raise self.prepare_error
        return config

    async def activate(self, candidate: Any) -> None:
        self.applied.append(candidate)

    async def discard(self, candidate: Any) -> None:
        self.discarded.append(candidate)

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
        "runtime_status": "online",
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


def test_failed_candidate_prepare_keeps_database_and_runtime_unchanged(
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
                "token": "old-secret",
            },
        )
        old_ciphertext = stored_ciphertext(settings)
        runtime.prepare_error = RuntimeError("candidate recovery failed")

        with pytest.raises(RuntimeError, match="candidate recovery failed"):
            client.put(
                "/api/v1/master-settings",
                headers=headers,
                json={
                    "scheme": "http",
                    "host": "candidate.example.com",
                    "port": 8080,
                    "token": "candidate-secret",
                },
            )
        current_ciphertext = stored_ciphertext(settings)
        current_address = stored_address(settings)
    finally:
        clients.close()

    assert saved.status_code == 200
    assert current_ciphertext == old_ciphertext
    assert current_address == ("https", "old-master.example.com", 443)
    assert len(runtime.applied) == 1


def test_failed_database_commit_keeps_old_runtime_and_discards_candidate(
    settings: Settings,
) -> None:
    from app.api.deps import get_session

    class CommitFailingSession:
        def __init__(self, session: Any) -> None:
            self.session = session

        def __getattr__(self, name: str) -> Any:
            return getattr(self.session, name)

        async def commit(self) -> None:
            raise RuntimeError("settings commit failed")

    clients = configured_client(settings)
    client, runtime = next(clients)
    headers = auth_headers(client)
    try:
        seeded = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "https",
                "host": "old-master.example.com",
                "port": 443,
                "token": "old-secret",
            },
        )
        old_runtime = runtime.applied[-1]
        old_ciphertext = stored_ciphertext(settings)

        async def failing_session():
            async with client.app.state.session_factory() as session:
                yield CommitFailingSession(session)

        client.app.dependency_overrides[get_session] = failing_session
        with pytest.raises(RuntimeError, match="settings commit failed"):
            client.put(
                "/api/v1/master-settings",
                headers=headers,
                json={
                    "scheme": "http",
                    "host": "candidate.example.com",
                    "port": 8080,
                    "token": "candidate-secret",
                },
            )
        client.app.dependency_overrides.clear()
        current_ciphertext = stored_ciphertext(settings)
        current_address = stored_address(settings)
    finally:
        client.app.dependency_overrides.clear()
        clients.close()

    assert seeded.status_code == 200
    assert current_ciphertext == old_ciphertext
    assert current_address == ("https", "old-master.example.com", 443)
    assert runtime.applied == [old_runtime]
    assert len(runtime.discarded) == 1
    assert runtime.discarded[0].host == "candidate.example.com"


def test_concurrent_empty_and_new_token_updates_stay_consistent(
    settings: Settings,
) -> None:
    clients = configured_client(settings)
    client, runtime = next(clients)
    headers = auth_headers(client)
    try:
        seeded = client.put(
            "/api/v1/master-settings",
            headers=headers,
            json={
                "scheme": "https",
                "host": "seed.example.com",
                "port": 443,
                "token": "seed-secret",
            },
        )
        runtime.test_delay = 0.05
        with ThreadPoolExecutor(max_workers=2) as pool:
            empty_future = pool.submit(
                client.put,
                "/api/v1/master-settings",
                headers=headers,
                json={
                    "scheme": "http",
                    "host": "empty-token.example.com",
                    "port": 8080,
                    "token": "",
                },
            )
            new_future = pool.submit(
                client.put,
                "/api/v1/master-settings",
                headers=headers,
                json={
                    "scheme": "https",
                    "host": "new-token.example.com",
                    "port": 9443,
                    "token": "new-secret",
                },
            )
            responses = [empty_future.result(), new_future.result()]
        final_address = stored_address(settings)
        final_token = CredentialCipher(settings.credential_key).decrypt(
            stored_ciphertext(settings)
        )
        final_runtime = runtime.applied[-1]
    finally:
        clients.close()

    assert seeded.status_code == 200
    assert [response.status_code for response in responses] == [200, 200]
    assert runtime.maximum_reconfiguring == 1
    assert final_address == (
        final_runtime.scheme,
        final_runtime.host,
        final_runtime.port,
    )
    assert final_token == final_runtime.token


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


@pytest.mark.asyncio
async def test_hot_candidate_never_recovers_executing_deployments(
    settings: Settings,
) -> None:
    from sqlalchemy import select

    from app.core.database import Base, create_engine, create_session_factory
    from app.models.deployment import DeploymentTarget, DeploymentTask
    from app.services.master_runtime import MasterRuntime
    from app.services.master_settings import MasterConfig

    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        session.add(
            DeploymentTask(
                master_task_id="executing-during-settings-update",
                artifact_url="https://artifacts.example/app.jar",
                artifact_sha256="a" * 64,
                artifact_name="app.jar",
                status="running",
                targets=[
                    DeploymentTarget(
                        target_ip="10.0.0.10",
                        target_directory="/opt/apps/example",
                        command="systemctl restart example",
                        status="executing",
                    )
                ],
            )
        )
        await session.commit()

    tracker = RuntimeTracker()

    def client_factory(base_url: str, node_id: str, token: str) -> FakeRuntimeClient:
        del base_url, node_id
        return FakeRuntimeClient(token, tracker)

    def inventory_factory(
        active_settings: Settings,
        active_session_factory: Any,
        client: FakeRuntimeClient,
    ) -> FakeInventory:
        del active_settings, active_session_factory
        return FakeInventory(client, tracker)

    runtime = MasterRuntime(
        settings=settings,
        session_factory=session_factory,
        artifact_service=object(),
        gateway=object(),
        cipher=CredentialCipher(settings.credential_key),
        client_factory=client_factory,
        inventory_factory=inventory_factory,
        start_worker=True,
    )
    config = MasterConfig("https", "master.example.com", 443, "secret")

    try:
        candidate = await runtime.prepare(config)
        await runtime.discard(candidate)
        async with session_factory() as session:
            hot_status = await session.scalar(select(DeploymentTarget.status))

        await runtime.apply(config, recover=True)
        async with session_factory() as session:
            cold_status = await session.scalar(select(DeploymentTarget.status))
    finally:
        await runtime.stop()
        await engine.dispose()

    assert hot_status == "executing"
    assert cold_status == "manual_review"


class RuntimeTracker:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.active_workers = 0
        self.maximum_workers = 0
        self.fail_recovery = False
        self.fail_notify_count = 0
        self.fail_worker_count = 0
        self.fail_executor_close_count = 0
        self.fail_client_close_count = 0
        self.executor_close_started: asyncio.Event | None = None
        self.executor_close_release: asyncio.Event | None = None


class FakeRuntimeClient:
    def __init__(self, token: str, tracker: RuntimeTracker) -> None:
        self.token = token
        self.tracker = tracker

    async def close(self) -> None:
        self.tracker.events.append(f"client-close:{self.token}")
        if self.tracker.fail_client_close_count:
            self.tracker.fail_client_close_count -= 1
            raise RuntimeError("client close failed")


class FakeInventory:
    def __init__(self, client: FakeRuntimeClient, tracker: RuntimeTracker) -> None:
        self.client = client
        self.tracker = tracker
        self.status = "connecting"

    def notify_change(self) -> None:
        self.tracker.events.append(f"notify:{self.client.token}")
        if self.tracker.fail_notify_count:
            self.tracker.fail_notify_count -= 1
            raise RuntimeError("notify failed")

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
        if self.tracker.fail_worker_count:
            self.tracker.fail_worker_count -= 1
            raise RuntimeError("worker stop failed")


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
        if self.tracker.executor_close_started is not None:
            self.tracker.executor_close_started.set()
        if self.tracker.executor_close_release is not None:
            await self.tracker.executor_close_release.wait()
        if self.tracker.fail_executor_close_count:
            self.tracker.fail_executor_close_count -= 1
            raise RuntimeError("executor close failed")


def runtime_with_fakes(
    settings: Settings,
    tracker: RuntimeTracker,
    *,
    task_factory: Any = None,
) -> Any:
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

    runtime_kwargs = {
        "settings": settings,
        "session_factory": object(),
        "artifact_service": object(),
        "gateway": object(),
        "cipher": CredentialCipher(settings.credential_key),
        "client_factory": client_factory,
        "inventory_factory": inventory_factory,
        "executor_factory": executor_factory,
        "start_worker": True,
    }
    if task_factory is not None:
        runtime_kwargs["task_factory"] = task_factory
    return MasterRuntime(
        **runtime_kwargs,
    )


async def route_runtime_with_old_settings(
    settings: Settings,
    tracker: RuntimeTracker,
) -> tuple[Any, Any, Any, Any, Any]:
    from app.core.database import Base, create_engine, create_session_factory
    from app.schemas.master_setting import MasterSettingInput
    from app.services.master_runtime import MasterRuntime
    from app.services.master_settings import MasterConfig, MasterSettingsService

    engine = create_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    runtime: MasterRuntime = runtime_with_fakes(settings, tracker)
    old_config = MasterConfig("https", "old.example.com", 443, "old")
    await runtime.apply(old_config)
    await asyncio.sleep(0)
    async with session_factory() as session:
        await MasterSettingsService(
            session,
            settings,
            CredentialCipher(settings.credential_key),
        ).save(
            MasterSettingInput(
                scheme=old_config.scheme,
                host=old_config.host,
                port=old_config.port,
                token=old_config.token,
            ),
            old_config,
        )
        await session.commit()

    async def skip_connection_test(config: MasterConfig) -> None:
        del config

    runtime.test = skip_connection_test  # type: ignore[method-assign]
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                master_runtime=runtime,
                settings=settings,
            )
        )
    )
    return engine, session_factory, runtime, request, old_config


class CommitAndRollbackFailingSession:
    def __init__(self, session: Any, rollback_error: BaseException) -> None:
        self.session = session
        self.rollback_error = rollback_error

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)

    async def commit(self) -> None:
        raise RuntimeError("settings commit failed")

    async def rollback(self) -> None:
        raise self.rollback_error


@pytest.mark.asyncio
async def test_cancelled_real_sqlite_commit_keeps_database_runtime_and_token_aligned(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aiosqlite

    from app.api.v1.master_settings import update_master_settings
    from app.schemas.master_setting import MasterSettingInput
    from app.services.master_settings import MasterSettingsService

    tracker = RuntimeTracker()
    engine, session_factory, runtime, request, _ = (
        await route_runtime_with_old_settings(settings, tracker)
    )
    commit_started = threading.Event()
    commit_release = threading.Event()
    original_execute = aiosqlite.Connection._execute
    gated_commit = False

    async def gated_execute(
        connection: aiosqlite.Connection,
        function: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal gated_commit
        if not gated_commit and getattr(function, "__name__", "") == "commit":
            gated_commit = True

            def commit_after_release() -> Any:
                commit_started.set()
                if not commit_release.wait(timeout=5):
                    raise TimeoutError("test did not release SQLite commit")
                return function(*args, **kwargs)

            return await original_execute(connection, commit_after_release)
        return await original_execute(connection, function, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, "_execute", gated_execute)
    update = MasterSettingInput(
        scheme="http",
        host="committed.example.com",
        port=8080,
        token="committed-token",
    )

    try:
        async with session_factory() as session:
            update_task = asyncio.create_task(
                update_master_settings(
                    update,
                    request,
                    session,
                    None,  # type: ignore[arg-type]
                )
            )
            assert await asyncio.to_thread(commit_started.wait, 5)
            update_task.cancel()
            commit_release.set()
            with pytest.raises(asyncio.CancelledError):
                await update_task

        async with session_factory() as session:
            saved = await MasterSettingsService(
                session,
                settings,
                CredentialCipher(settings.credential_key),
            ).get_effective()

        assert saved.host == "committed.example.com"
        assert saved.token == "committed-token"
        assert runtime._active is not None
        assert runtime._active.config.host == saved.host
        assert runtime._active.config.token == saved.token
        assert tracker.active_workers == 1
    finally:
        commit_release.set()
        await runtime.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_reports_unconfigured_connecting_and_stopped(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    runtime = runtime_with_fakes(settings, tracker)

    await runtime.apply(MasterConfig("https", "", 443, ""))
    assert runtime.status == "unconfigured"

    await runtime.apply(
        MasterConfig("https", "master.example.com", 443, "secret")
    )
    assert runtime.status == "connecting"

    await runtime.stop()
    assert runtime.status == "stopped"


@pytest.mark.asyncio
async def test_put_activates_committed_candidate_when_old_closers_fail(
    settings: Settings,
) -> None:
    from app.api.v1.master_settings import update_master_settings
    from app.schemas.master_setting import MasterSettingInput
    from app.services.master_settings import MasterSettingsService

    tracker = RuntimeTracker()
    engine, session_factory, runtime, request, _ = (
        await route_runtime_with_old_settings(settings, tracker)
    )
    tracker.fail_worker_count = 1
    tracker.fail_executor_close_count = 1
    tracker.fail_client_close_count = 1
    new_data = MasterSettingInput(
        scheme="http",
        host="new.example.com",
        port=8080,
        token="new",
    )

    try:
        async with session_factory() as session:
            result = await update_master_settings(
                new_data,
                request,
                session,
                None,  # type: ignore[arg-type]
            )
        await asyncio.sleep(0)
        async with session_factory() as session:
            saved = await MasterSettingsService(
                session,
                settings,
                CredentialCipher(settings.credential_key),
            ).get_effective()

        assert result.host == "new.example.com"
        assert saved.host == "new.example.com"
        assert saved.token == "new"
        assert tracker.events.count("worker-stop:old") == 1
        assert tracker.events.count("worker-start:new") == 1
        assert tracker.events.count("executor-close:old") == 1
        assert tracker.events.count("client-close:old") == 1
        assert tracker.active_workers == 1
        assert tracker.maximum_workers == 1
        assert runtime.status == "connecting"

        await runtime.stop()

        assert tracker.events.count("executor-close:old") == 2
        assert tracker.events.count("client-close:old") == 2
        assert tracker.events.count("executor-close:new") == 1
        assert tracker.events.count("client-close:new") == 1
    finally:
        await runtime.stop()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rollback_error",
    [
        RuntimeError("settings rollback failed"),
        asyncio.CancelledError("settings rollback cancelled"),
    ],
    ids=["rollback-error", "rollback-cancelled"],
)
async def test_failed_rollback_still_discards_prepared_candidate(
    settings: Settings,
    rollback_error: BaseException,
) -> None:
    from app.api.v1.master_settings import update_master_settings
    from app.schemas.master_setting import MasterSettingInput
    from app.services.master_settings import MasterConfig, MasterSettingsService

    tracker = RuntimeTracker()
    engine, session_factory, runtime, request, old_config = (
        await route_runtime_with_old_settings(settings, tracker)
    )
    prepared: list[Any] = []
    original_prepare = runtime.prepare

    async def capture_candidate(config: MasterConfig) -> Any:
        candidate = await original_prepare(config)
        prepared.append(candidate)
        return candidate

    runtime.prepare = capture_candidate  # type: ignore[method-assign]
    session = session_factory()
    failure: BaseException | None = None
    try:
        try:
            await update_master_settings(
                MasterSettingInput(
                    scheme="http",
                    host="candidate.example.com",
                    port=8080,
                    token="candidate",
                ),
                request,
                CommitAndRollbackFailingSession(session, rollback_error),
                None,  # type: ignore[arg-type]
            )
        except BaseException as exc:
            failure = exc
        finally:
            await session.close()

        assert prepared
        candidate = prepared[0]
        assert not candidate.has_resources
        assert candidate.worker is None
        assert candidate.executor is None
        assert candidate.client is None
        assert tracker.events.count("executor-close:candidate") == 1
        assert tracker.events.count("client-close:candidate") == 1
        assert "worker-stop:old" not in tracker.events
        assert tracker.active_workers == 1
        assert runtime.status == "connecting"

        async with session_factory() as query_session:
            saved = await MasterSettingsService(
                query_session,
                settings,
                CredentialCipher(settings.credential_key),
            ).get_effective()
        assert saved == old_config
        assert isinstance(failure, RuntimeError)
        assert str(failure) == "settings commit failed"
        assert any(
            "rollback failed" in note
            for note in getattr(failure, "__notes__", ())
        )
    finally:
        if prepared and prepared[0].has_resources:
            await runtime.discard(prepared[0])
        await runtime.stop()
        await engine.dispose()


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
    assert runtime.status == "connecting"

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
async def test_candidate_recovery_failure_keeps_old_runtime_running(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    runtime = runtime_with_fakes(settings, tracker)
    await runtime.apply(MasterConfig("https", "old.example.com", 443, "old"))
    await asyncio.sleep(0)
    tracker.fail_recovery = True

    with pytest.raises(RuntimeError, match="recovery failed"):
        await runtime.apply(
            MasterConfig("https", "candidate.example.com", 443, "candidate"),
            recover=True,
        )

    assert "worker-stop:old" not in tracker.events
    assert "client-close:old" not in tracker.events
    assert tracker.events.count("executor-close:candidate") == 1
    assert tracker.events.count("client-close:candidate") == 1
    assert tracker.active_workers == 1
    assert tracker.maximum_workers == 1
    assert runtime.status == "connecting"

    await runtime.stop()


@pytest.mark.asyncio
async def test_candidate_worker_task_start_failure_keeps_old_runtime_running(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    task_count = 0

    def task_factory(coro: Any, *, name: str) -> asyncio.Task[None]:
        nonlocal task_count
        task_count += 1
        if task_count == 2:
            coro.close()
            raise RuntimeError("worker task start failed")
        return asyncio.create_task(coro, name=name)

    runtime = runtime_with_fakes(
        settings,
        tracker,
        task_factory=task_factory,
    )
    await runtime.apply(MasterConfig("https", "old.example.com", 443, "old"))
    await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="worker task start failed"):
        await runtime.apply(
            MasterConfig("https", "candidate.example.com", 443, "candidate")
        )

    assert "worker-stop:old" not in tracker.events
    assert "client-close:old" not in tracker.events
    assert tracker.events.count("executor-close:candidate") == 1
    assert tracker.events.count("client-close:candidate") == 1
    assert tracker.active_workers == 1
    assert tracker.maximum_workers == 1

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
        await runtime.apply(
            MasterConfig("https", "master.example.com", 443, "secret"),
            recover=True,
        )

    assert tracker.events.count("executor-close:secret") == 1
    assert tracker.events.count("client-close:secret") == 1
    assert runtime.status == "stopped"


@pytest.mark.asyncio
async def test_stop_attempts_all_cleanup_and_retries_failed_resources(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    runtime = runtime_with_fakes(settings, tracker)
    await runtime.apply(MasterConfig("https", "master.example.com", 443, "secret"))
    await asyncio.sleep(0)
    tracker.fail_notify_count = 1
    tracker.fail_worker_count = 1
    tracker.fail_executor_close_count = 1
    tracker.fail_client_close_count = 1

    with pytest.raises(ExceptionGroup) as cleanup_error:
        await runtime.stop()

    assert len(cleanup_error.value.exceptions) == 4
    assert tracker.events.count("worker-stop:secret") == 1
    assert tracker.events.count("executor-close:secret") == 1
    assert tracker.events.count("client-close:secret") == 1
    assert runtime.status == "stopped"

    await runtime.stop()

    assert tracker.events.count("executor-close:secret") == 2
    assert tracker.events.count("client-close:secret") == 2


@pytest.mark.asyncio
async def test_cancelled_stop_finishes_cleanup_without_losing_owned_slot(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    tracker.executor_close_started = asyncio.Event()
    tracker.executor_close_release = asyncio.Event()
    runtime = runtime_with_fakes(settings, tracker)
    await runtime.apply(MasterConfig("https", "master.example.com", 443, "secret"))
    await asyncio.sleep(0)

    stop_task = asyncio.create_task(runtime.stop())
    await tracker.executor_close_started.wait()
    stop_task.cancel()
    tracker.executor_close_release.set()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert tracker.events.count("worker-stop:secret") == 1
    assert tracker.events.count("executor-close:secret") == 1
    assert tracker.events.count("client-close:secret") == 1
    assert runtime.status == "stopped"

    await runtime.stop()


@pytest.mark.asyncio
async def test_cancelled_activation_completes_atomic_swap_with_one_worker(
    settings: Settings,
) -> None:
    from app.services.master_settings import MasterConfig

    tracker = RuntimeTracker()
    runtime = runtime_with_fakes(settings, tracker)
    await runtime.apply(MasterConfig("https", "old.example.com", 443, "old"))
    await asyncio.sleep(0)
    candidate = await runtime.prepare(
        MasterConfig("https", "candidate.example.com", 443, "candidate")
    )
    tracker.executor_close_started = asyncio.Event()
    tracker.executor_close_release = asyncio.Event()

    activation_task = asyncio.create_task(runtime.activate(candidate))
    await tracker.executor_close_started.wait()
    activation_task.cancel()
    tracker.executor_close_release.set()

    try:
        with pytest.raises(asyncio.CancelledError):
            await activation_task
        await asyncio.sleep(0)

        assert tracker.events.count("worker-stop:old") == 1
        assert tracker.events.count("client-close:old") == 1
        assert tracker.events.count("worker-start:candidate") == 1
        assert tracker.active_workers == 1
        assert tracker.maximum_workers == 1
        assert runtime.status == "connecting"
    finally:
        tracker.executor_close_release.set()
        await runtime.discard(candidate)
        await runtime.stop()


def test_lifespan_cleans_runtime_when_startup_apply_fails(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.master_runtime import MasterRuntime

    stopped: list[bool] = []

    async def fail_apply(
        runtime: MasterRuntime,
        config: Any,
        *,
        recover: bool = False,
    ) -> None:
        del runtime, config, recover
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


def test_lifespan_cleans_artifact_client_and_engine_on_early_init_failure(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncEngine

    import app.main as main_module

    artifact_closed: list[bool] = []
    engine_disposed: list[bool] = []
    original_dispose = AsyncEngine.dispose

    class FakeArtifactHttp:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        async def aclose(self) -> None:
            artifact_closed.append(True)

    class FailingRuntime:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs
            raise RuntimeError("runtime init failed")

    async def tracked_dispose(engine: AsyncEngine, *args: Any, **kwargs: Any) -> None:
        engine_disposed.append(True)
        await original_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeArtifactHttp)
    monkeypatch.setattr(main_module, "MasterRuntime", FailingRuntime)
    monkeypatch.setattr(AsyncEngine, "dispose", tracked_dispose)

    with pytest.raises(RuntimeError, match="runtime init failed"):
        with TestClient(create_app(settings)):
            pass

    assert artifact_closed == [True]
    assert engine_disposed == [True]


def test_lifespan_attempts_artifact_and_engine_cleanup_when_runtime_stop_fails(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncEngine

    import app.main as main_module
    from app.services.master_runtime import MasterRuntime

    artifact_closed: list[bool] = []
    engine_disposed: list[bool] = []
    original_dispose = AsyncEngine.dispose

    class FakeArtifactHttp:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        async def aclose(self) -> None:
            artifact_closed.append(True)

    async def no_op_apply(
        runtime: MasterRuntime,
        config: Any,
        *,
        recover: bool = False,
    ) -> None:
        del runtime, config, recover

    async def fail_stop(runtime: MasterRuntime) -> None:
        del runtime
        raise RuntimeError("runtime stop failed")

    async def tracked_dispose(engine: AsyncEngine, *args: Any, **kwargs: Any) -> None:
        engine_disposed.append(True)
        await original_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeArtifactHttp)
    monkeypatch.setattr(MasterRuntime, "apply", no_op_apply)
    monkeypatch.setattr(MasterRuntime, "stop", fail_stop)
    monkeypatch.setattr(AsyncEngine, "dispose", tracked_dispose)

    with pytest.raises(RuntimeError, match="runtime stop failed"):
        with TestClient(create_app(settings)):
            pass

    assert artifact_closed == [True]
    assert engine_disposed == [True]


def test_lifespan_attempts_artifact_and_engine_cleanup_on_cancellation(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.ext.asyncio import AsyncEngine

    import app.main as main_module
    from app.services.master_runtime import MasterRuntime

    artifact_closed: list[bool] = []
    engine_disposed: list[bool] = []
    original_dispose = AsyncEngine.dispose

    class FakeArtifactHttp:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        async def aclose(self) -> None:
            artifact_closed.append(True)

    async def no_op_apply(
        runtime: MasterRuntime,
        config: Any,
        *,
        recover: bool = False,
    ) -> None:
        del runtime, config, recover

    async def cancel_stop(runtime: MasterRuntime) -> None:
        del runtime
        raise asyncio.CancelledError

    async def tracked_dispose(engine: AsyncEngine, *args: Any, **kwargs: Any) -> None:
        engine_disposed.append(True)
        await original_dispose(engine, *args, **kwargs)

    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeArtifactHttp)
    monkeypatch.setattr(MasterRuntime, "apply", no_op_apply)
    monkeypatch.setattr(MasterRuntime, "stop", cancel_stop)
    monkeypatch.setattr(AsyncEngine, "dispose", tracked_dispose)

    with pytest.raises((asyncio.CancelledError, FutureCancelledError)):
        with TestClient(create_app(settings)):
            pass

    assert artifact_closed == [True]
    assert engine_disposed == [True]
