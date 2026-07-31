import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.inventory_sync import build_inventory


def test_inventory_payload_omits_credentials_and_contains_runtime_state():
    payload = build_inventory(
        node_id="node-1",
        node_name="Shanghai child",
        version="0.1.0",
        hosts=[
            {
                "id": "host-1",
                "name": "web-01",
                "address": "10.0.0.10",
                "port": 22,
                "username": "root",
                "tags": ["production"],
                "is_local": True,
                "last_test_status": "success",
                "last_test_code": "SSH_CONNECTED",
                "last_tested_at": datetime(2026, 8, 1, 8, tzinfo=UTC),
                "last_test_message": "SSH 连接成功",
                "encrypted_password": "must-not-leak",
            }
        ],
    )

    assert payload["protocol_version"] == "v1"
    assert payload["node"]["id"] == "node-1"
    assert payload["node"]["reported_at"].endswith("Z")
    assert payload["hosts"][0] == {
        "id": "host-1",
        "name": "web-01",
        "address": "10.0.0.10",
        "port": 22,
        "username": "root",
        "tags": ["production"],
        "is_local": True,
        "last_test_status": "success",
        "last_test_code": "SSH_CONNECTED",
        "last_tested_at": "2026-08-01T08:00:00Z",
    }
    assert "password" not in str(payload)
    assert "SSH 连接成功" not in str(payload)


def test_inventory_change_wakes_background_sync():
    from app.services.inventory_sync import InventorySynchronizer

    synchronizer = InventorySynchronizer(None, None)
    assert synchronizer.changed.is_set() is False

    synchronizer.notify_change()

    assert synchronizer.changed.is_set() is True


class EmptyScalars:
    def all(self) -> list[Any]:
        return []


class EmptySession:
    async def scalars(self, query: Any) -> EmptyScalars:
        del query
        return EmptyScalars()


@asynccontextmanager
async def empty_session_factory():
    yield EmptySession()


class HeartbeatClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def heartbeat(self, payload: dict[str, Any]) -> None:
        assert payload["node"]["id"] == "node-1"
        self.calls += 1
        if self.error is not None:
            raise self.error


def synchronizer(client: HeartbeatClient):
    from app.services.inventory_sync import InventorySynchronizer

    settings = SimpleNamespace(
        node_id="node-1",
        node_name="Shanghai child",
        node_version="0.1.0",
    )
    return InventorySynchronizer(settings, empty_session_factory, client)


@pytest.mark.asyncio
async def test_successful_heartbeat_and_poll_report_online() -> None:
    client = HeartbeatClient()
    sync = synchronizer(client)
    stop = asyncio.Event()

    async def successful_poll() -> None:
        stop.set()
        sync.notify_change()

    assert sync.status == "connecting"
    await sync.run(stop, successful_poll)

    assert client.calls == 1
    assert sync.status == "online"
    assert sync.last_success_at is not None


@pytest.mark.asyncio
async def test_heartbeat_connection_failure_reports_error() -> None:
    client = HeartbeatClient(OSError("master unreachable"))
    sync = synchronizer(client)

    with pytest.raises(OSError, match="master unreachable"):
        await sync.sync_now()

    assert sync.status == "error"


@pytest.mark.asyncio
async def test_poll_failure_after_heartbeat_reports_error() -> None:
    client = HeartbeatClient()
    sync = synchronizer(client)
    stop = asyncio.Event()

    async def failing_poll() -> None:
        stop.set()
        sync.notify_change()
        raise OSError("claim failed")

    await sync.run(stop, failing_poll)

    assert client.calls == 1
    assert sync.status == "error"


@pytest.mark.asyncio
async def test_normal_inventory_sync_waits_sixty_seconds_between_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HeartbeatClient()
    sync = synchronizer(client)
    stop = asyncio.Event()
    observed_timeouts: list[float] = []

    async def stop_after_wait(awaitable: Any, **options: float) -> None:
        observed_timeouts.append(options["timeout"])
        awaitable.close()
        stop.set()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", stop_after_wait)

    await sync.run(stop)

    assert observed_timeouts == [60]
    assert client.calls == 1


@pytest.mark.asyncio
async def test_failed_changed_inventory_waits_before_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = HeartbeatClient(OSError("master rejected heartbeat"))
    sync = synchronizer(client)
    sync.notify_change()
    stop = asyncio.Event()
    event_states_at_wait: list[bool] = []

    async def stop_after_wait(awaitable: Any, **options: float) -> None:
        assert options["timeout"] == 60
        event_states_at_wait.append(sync.changed.is_set())
        awaitable.close()
        stop.set()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", stop_after_wait)

    await sync.run(stop)

    assert event_states_at_wait == [False]
    assert client.calls == 1
