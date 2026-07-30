import asyncio
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncssh
import pytest
from fastapi import WebSocketDisconnect

from app.services.ssh import HostConnection
from app.services.terminal import AsyncTerminal, AsyncTerminalGateway, bridge_terminal


def auth_headers(client) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_trusted_host(client, headers) -> dict:
    host = client.post(
        "/api/v1/hosts",
        headers=headers,
        json={
            "name": "terminal-host",
            "address": "10.0.0.20",
            "port": 22,
            "username": "root",
            "password": "SshPassw0rd!",
            "tags": [],
            "is_local": False,
        },
    ).json()
    return client.post(
        f"/api/v1/hosts/{host['id']}/trust-fingerprint",
        headers=headers,
        json={"fingerprint": "SHA256:trusted"},
    ).json()


def test_terminal_ticket_is_one_use_and_short_lived(client):
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)

    response = client.post(
        "/api/v1/terminal/tickets",
        headers=headers,
        json={"host_id": host["id"]},
    )

    assert response.status_code == 201
    ticket = response.json()
    assert ticket["ticket"]
    expires_at = datetime.fromisoformat(ticket["expires_at"])
    assert expires_at <= datetime.now(UTC) + timedelta(seconds=31)

    store = client.app.state.terminal_tickets
    assert store.consume(ticket["ticket"], host["id"]).user_id
    assert store.consume(ticket["ticket"], host["id"]) is None


def test_untrusted_host_cannot_issue_terminal_ticket(client):
    headers = auth_headers(client)
    host = client.post(
        "/api/v1/hosts",
        headers=headers,
        json={
            "name": "untrusted",
            "address": "10.0.0.21",
            "port": 22,
            "username": "root",
            "password": "SshPassw0rd!",
            "tags": [],
            "is_local": False,
        },
    ).json()

    response = client.post(
        "/api/v1/terminal/tickets",
        headers=headers,
        json={"host_id": host["id"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SSH_HOST_UNTRUSTED"


class FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.eof_calls = 0

    def write(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("binary terminal stdin requires bytes")
        self.writes.append(data)

    def write_eof(self) -> None:
        self.eof_calls += 1


class BlockingStdout:
    async def read(self, _: int) -> bytes:
        await asyncio.Event().wait()
        return b""


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = FakeStdin()
        self.stdout = BlockingStdout()


class FakeConnection:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    async def wait_closed(self) -> None:
        pass


class InputWebSocket:
    def __init__(self) -> None:
        self.messages = [{"type": "input", "data": b64encode(b"ls\r").decode()}]

    async def send_json(self, message: dict[str, str]) -> None:
        pass

    async def receive_json(self) -> dict[str, str]:
        if self.messages:
            return self.messages.pop()
        raise WebSocketDisconnect()


@pytest.mark.asyncio
async def test_binary_terminal_bridge_writes_browser_input_as_bytes():
    process = FakeProcess()
    connection = FakeConnection()
    terminal = AsyncTerminal(connection, process)

    await bridge_terminal(InputWebSocket(), terminal)

    assert process.stdin.writes == [b"ls\r"]
    assert process.stdin.eof_calls == 1
    assert connection.close_calls == 1


class FailingTerminal:
    def __init__(self) -> None:
        self.close_calls = 0

    async def read(self) -> bytes:
        raise RuntimeError("remote channel failed")

    def write(self, data: bytes) -> None:
        pass

    def resize(self, cols: int, rows: int) -> None:
        pass

    async def close(self) -> None:
        self.close_calls += 1


class WaitingWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_json(self, message: dict[str, str]) -> None:
        self.sent.append(message)

    async def receive_json(self) -> dict[str, str]:
        await asyncio.Event().wait()
        return {"type": "input", "data": b64encode(b"x").decode()}


@pytest.mark.asyncio
async def test_terminal_bridge_reports_remote_failure_and_closes_terminal():
    websocket = WaitingWebSocket()
    terminal = FailingTerminal()

    await bridge_terminal(websocket, terminal)

    assert websocket.sent == [
        {"type": "error", "code": "TERMINAL_BRIDGE_ERROR"}
    ]
    assert terminal.close_calls == 1


class ErroringErrorWebSocket(WaitingWebSocket):
    async def send_json(self, message: dict[str, str]) -> None:
        if message["type"] == "error":
            raise RuntimeError("websocket send failed")
        await super().send_json(message)


@pytest.mark.asyncio
async def test_terminal_bridge_closes_when_error_frame_cannot_be_sent():
    websocket = ErroringErrorWebSocket()
    terminal = FailingTerminal()

    await bridge_terminal(websocket, terminal)

    assert terminal.close_calls == 1


class RaceTerminal(FailingTerminal):
    async def read(self) -> bytes:
        return b"output"


class DisconnectingOutputWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_json(self, message: dict[str, str]) -> None:
        if message["type"] == "output":
            await asyncio.sleep(0)
            raise WebSocketDisconnect()
        self.sent.append(message)

    async def receive_json(self) -> dict[str, str]:
        await asyncio.sleep(0)
        return {"type": "resize", "cols": "bad", "rows": "1"}


@pytest.mark.asyncio
async def test_terminal_bridge_prioritizes_non_disconnect_failure():
    websocket = DisconnectingOutputWebSocket()
    terminal = RaceTerminal()

    await bridge_terminal(websocket, terminal)

    assert websocket.sent == [
        {"type": "error", "code": "TERMINAL_BRIDGE_ERROR"}
    ]
    assert terminal.close_calls == 1


class RejectingTerminalGateway:
    def __init__(
        self,
        error: Exception | None = None,
    ) -> None:
        self.connection: HostConnection | None = None
        self.error = error or asyncssh.HostKeyNotVerifiable(
            "Host key is not trusted"
        )

    async def open(
        self,
        connection: HostConnection,
        cols: int,
        rows: int,
    ) -> None:
        del cols, rows
        self.connection = connection
        raise self.error


def test_terminal_websocket_reports_changed_host_key_and_passes_saved_pin(client):
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)
    ticket = client.post(
        "/api/v1/terminal/tickets",
        headers=headers,
        json={"host_id": host["id"]},
    ).json()["ticket"]
    gateway = RejectingTerminalGateway()
    client.app.state.terminal_gateway = gateway

    with client.websocket_connect(f"/api/v1/terminal/ws/{host['id']}") as websocket:
        websocket.send_json({"ticket": ticket, "cols": 120, "rows": 36})
        assert websocket.receive_json() == {
            "type": "error",
            "code": "TERMINAL_HOST_KEY_CHANGED",
        }

    assert gateway.connection is not None
    assert gateway.connection.host_key_fingerprint == "SHA256:trusted"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (asyncssh.PermissionDenied("password rejected"), "TERMINAL_AUTH_FAILED"),
        (OSError("network unreachable"), "TERMINAL_NETWORK_ERROR"),
        (asyncssh.ChannelOpenError(1, "session refused"), "TERMINAL_CHANNEL_ERROR"),
        (RuntimeError("unexpected open failure"), "TERMINAL_OPEN_ERROR"),
    ],
)
def test_terminal_websocket_reports_stable_open_error_codes(
    client,
    error: Exception,
    code: str,
) -> None:
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)
    ticket = client.post(
        "/api/v1/terminal/tickets",
        headers=headers,
        json={"host_id": host["id"]},
    ).json()["ticket"]
    client.app.state.terminal_gateway = RejectingTerminalGateway(error)

    with client.websocket_connect(f"/api/v1/terminal/ws/{host['id']}") as websocket:
        websocket.send_json({"ticket": ticket, "cols": 120, "rows": 36})
        assert websocket.receive_json() == {"type": "error", "code": code}


class ClassifiedFailingTerminal(FailingTerminal):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def read(self) -> bytes:
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (asyncssh.ChannelOpenError(1, "channel lost"), "TERMINAL_CHANNEL_ERROR"),
        (asyncssh.ConnectionLost("connection lost"), "TERMINAL_NETWORK_ERROR"),
    ],
)
async def test_terminal_bridge_classifies_channel_and_network_failures(
    error: Exception,
    code: str,
) -> None:
    websocket = WaitingWebSocket()
    terminal = ClassifiedFailingTerminal(error)

    await bridge_terminal(websocket, terminal)

    assert websocket.sent == [{"type": "error", "code": code}]
    assert terminal.close_calls == 1


class FailingProcessConnection:
    def __init__(self) -> None:
        self.close_calls = 0
        self.wait_calls = 0

    async def create_process(self, **kwargs: Any) -> None:
        del kwargs
        raise asyncssh.ChannelOpenError(1, "session refused")

    def close(self) -> None:
        self.close_calls += 1

    async def wait_closed(self) -> None:
        self.wait_calls += 1


@pytest.mark.asyncio
async def test_terminal_open_closes_ssh_when_process_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssh = FailingProcessConnection()

    async def connect(*args: Any, **kwargs: Any) -> FailingProcessConnection:
        del args, kwargs
        return ssh

    import app.services.terminal as terminal_module

    monkeypatch.setattr(terminal_module.asyncssh, "connect", connect)
    monkeypatch.setattr(terminal_module, "connect_ssh", connect, raising=False)

    with pytest.raises(asyncssh.ChannelOpenError):
        await AsyncTerminalGateway().open(
            HostConnection(
                "node.example.com",
                22,
                "root",
                "secret",
                host_key_fingerprint="SHA256:trusted",
            ),
            120,
            36,
        )

    assert ssh.close_calls == 1
    assert ssh.wait_calls == 1


class FailingCloseStdin:
    def __init__(self) -> None:
        self.eof_calls = 0

    def write_eof(self) -> None:
        self.eof_calls += 1
        raise RuntimeError("stdin EOF failed")


class FailingCloseProcess:
    def __init__(self) -> None:
        self.stdin = FailingCloseStdin()


class IndependentlyFailingConnection:
    def __init__(self) -> None:
        self.close_calls = 0
        self.wait_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        raise RuntimeError("connection close failed")

    async def wait_closed(self) -> None:
        self.wait_calls += 1


@pytest.mark.asyncio
async def test_terminal_close_attempts_every_cleanup_step_after_earlier_failures():
    process = FailingCloseProcess()
    connection = IndependentlyFailingConnection()
    terminal = AsyncTerminal(connection, process)

    with pytest.raises(BaseExceptionGroup):
        await terminal.close()

    assert process.stdin.eof_calls == 1
    assert connection.close_calls == 1
    assert connection.wait_calls == 1
