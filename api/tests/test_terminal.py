import asyncio
from base64 import b64encode
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import WebSocketDisconnect

from app.services.terminal import AsyncTerminal, bridge_terminal


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
