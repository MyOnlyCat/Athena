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

    def write(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("binary terminal stdin requires bytes")
        self.writes.append(data)

    def write_eof(self) -> None:
        pass


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = FakeStdin()


class FakeConnection:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


def test_binary_terminal_writes_browser_input_as_bytes():
    process = FakeProcess()
    terminal = AsyncTerminal(FakeConnection(), process)

    terminal.write(b"ls\r")

    assert process.stdin.writes == [b"ls\r"]


class FailingTerminal:
    def __init__(self) -> None:
        self.closed = False

    async def read(self) -> bytes:
        raise RuntimeError("remote channel failed")

    def write(self, data: bytes) -> None:
        pass

    def resize(self, cols: int, rows: int) -> None:
        pass

    async def close(self) -> None:
        self.closed = True


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
    assert terminal.closed is True


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
    assert terminal.closed is True
