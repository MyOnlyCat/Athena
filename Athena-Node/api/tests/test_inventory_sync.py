import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import AppError
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
    return InventorySynchronizer(
        settings,
        empty_session_factory,
        client,
        jitter_source=lambda: 0.5,
    )


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
async def test_heartbeat_connection_failure_reports_connection_state() -> None:
    client = HeartbeatClient(OSError("master unreachable"))
    sync = synchronizer(client)

    with pytest.raises(OSError, match="master unreachable"):
        await sync.sync_now()

    assert sync.status == "connection_failed"


@pytest.mark.asyncio
async def test_structured_master_unavailability_uses_connection_backoff() -> None:
    client = HeartbeatClient(
        AppError(
            "MASTER_TEMPORARILY_UNAVAILABLE",
            "主节点暂时不可用，请稍后重试",
            status_code=503,
        )
    )
    sync = synchronizer(client)

    with pytest.raises(AppError, match="主节点暂时不可用"):
        await sync.sync_now()

    assert sync.status == "connection_failed"
    assert sync._retry_delay() == 5


@pytest.mark.asyncio
async def test_poll_failure_does_not_change_heartbeat_connection_state() -> None:
    client = HeartbeatClient()
    sync = synchronizer(client)
    stop = asyncio.Event()

    async def failing_poll() -> None:
        stop.set()
        sync.notify_change()
        raise OSError("claim failed")

    await sync.run(stop, failing_poll)

    assert client.calls == 1
    assert sync.status == "online"


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
        assert options["timeout"] == 5
        event_states_at_wait.append(sync.changed.is_set())
        awaitable.close()
        stop.set()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", stop_after_wait)

    await sync.run(stop)

    assert event_states_at_wait == [False]
    assert client.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (AppError("NODE_DISABLED", "接入节点已被禁用", status_code=403), "disabled"),
        (
            AppError("NODE_SIGNATURE_INVALID", "节点签名无效", status_code=401),
            "authentication_failed",
        ),
    ],
)
async def test_management_and_authentication_failures_probe_every_five_minutes(
    monkeypatch: pytest.MonkeyPatch,
    error: AppError,
    expected_status: str,
) -> None:
    client = HeartbeatClient(error)
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

    assert observed_timeouts == [300]
    assert sync.status == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        AppError("NODE_NOT_APPROVED", "节点尚未批准", status_code=404),
        AppError(
            "REGISTRATION_REJECTED",
            "接入申请已被拒绝，请联系管理员恢复后手动重试",
            status_code=409,
        ),
    ],
)
async def test_unapproved_nodes_retry_after_normal_heartbeat_interval(
    monkeypatch: pytest.MonkeyPatch,
    error: AppError,
) -> None:
    client = HeartbeatClient(error)
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
    assert sync.status == "pending"


class SequencedHeartbeatClient(HeartbeatClient):
    def __init__(self, outcomes: list[Exception | None]) -> None:
        super().__init__()
        self.outcomes = outcomes

    async def heartbeat(self, payload: dict[str, Any]) -> None:
        assert payload["node"]["id"] == "node-1"
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if outcome is not None:
            raise outcome


@pytest.mark.asyncio
async def test_master_connection_backoff_is_jittered_capped_and_resets_after_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.inventory_sync import InventorySynchronizer

    failures = [OSError("master unreachable") for _ in range(7)]
    client = SequencedHeartbeatClient([*failures, None])
    settings = SimpleNamespace(
        node_id="node-1",
        node_name="Shanghai child",
        node_version="0.1.0",
    )
    sync = InventorySynchronizer(
        settings,
        empty_session_factory,
        client,
        jitter_source=lambda: 0.5,
    )
    stop = asyncio.Event()
    observed_timeouts: list[float] = []

    async def observe_wait(awaitable: Any, **options: float) -> None:
        observed_timeouts.append(options["timeout"])
        awaitable.close()
        if len(observed_timeouts) == 8:
            stop.set()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", observe_wait)

    await sync.run(stop)

    assert observed_timeouts == [5, 10, 20, 40, 80, 160, 300, 60]
    assert max(observed_timeouts) == 300
    assert sync.status == "online"
    assert sync.last_success_at is not None
