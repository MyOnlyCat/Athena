import asyncio
import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Any

import asyncssh
from fastapi import WebSocket, WebSocketDisconnect

from app.core.errors import AppError
from app.services.ssh import HostConnection


@dataclass(frozen=True)
class TerminalTicket:
    value: str
    user_id: str
    host_id: str
    expires_at: datetime


class TerminalTicketStore:
    def __init__(self, ttl_seconds: int = 30) -> None:
        self.ttl_seconds = ttl_seconds
        self._tickets: dict[str, TerminalTicket] = {}
        self._active_sessions: dict[str, int] = {}

    def issue(self, user_id: str, host_id: str) -> TerminalTicket:
        if self._active_sessions.get(user_id, 0) >= 5:
            raise AppError("TERMINAL_SESSION_LIMIT", "终端会话数量已达上限", status_code=429)
        ticket = TerminalTicket(
            value=token_urlsafe(32),
            user_id=user_id,
            host_id=host_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=self.ttl_seconds),
        )
        self._tickets[ticket.value] = ticket
        return ticket

    def consume(self, value: str, host_id: str) -> TerminalTicket | None:
        ticket = self._tickets.pop(value, None)
        if ticket is None or ticket.host_id != host_id or ticket.expires_at < datetime.now(UTC):
            return None
        return ticket

    def opened(self, user_id: str) -> None:
        self._active_sessions[user_id] = self._active_sessions.get(user_id, 0) + 1

    def closed(self, user_id: str) -> None:
        count = self._active_sessions.get(user_id, 0)
        if count <= 1:
            self._active_sessions.pop(user_id, None)
        else:
            self._active_sessions[user_id] = count - 1


class AsyncTerminal:
    def __init__(self, connection: asyncssh.SSHClientConnection, process: Any) -> None:
        self.connection = connection
        self.process = process

    async def read(self) -> bytes:
        data = await self.process.stdout.read(4096)
        return data.encode() if isinstance(data, str) else data

    def write(self, data: bytes) -> None:
        self.process.stdin.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self.process.change_terminal_size(cols, rows)

    async def close(self) -> None:
        self.process.stdin.write_eof()
        self.connection.close()
        await self.connection.wait_closed()


class AsyncTerminalGateway:
    async def open(self, connection: HostConnection, cols: int, rows: int) -> AsyncTerminal:
        ssh = await asyncssh.connect(
            connection.address,
            port=connection.port,
            username=connection.username,
            password=connection.password,
            known_hosts=None,
        )
        process = await ssh.create_process(
            term_type="xterm-256color",
            term_size=(cols, rows),
            encoding=None,
        )
        return AsyncTerminal(ssh, process)


async def bridge_terminal(websocket: WebSocket, terminal: AsyncTerminal) -> None:
    async def remote_to_browser() -> None:
        while True:
            data = await terminal.read()
            if not data:
                return
            await websocket.send_json(
                {"type": "output", "data": base64.b64encode(data).decode()}
            )

    async def browser_to_remote() -> None:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")
            if message_type == "input":
                terminal.write(base64.b64decode(message.get("data", "")))
            elif message_type == "resize":
                terminal.resize(int(message["cols"]), int(message["rows"]))
            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})

    tasks = [
        asyncio.create_task(remote_to_browser()),
        asyncio.create_task(browser_to_remote()),
    ]
    try:
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, (asyncio.CancelledError, WebSocketDisconnect)):
                continue
            if isinstance(result, BaseException):
                raise result
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.send_json({"type": "error", "code": "TERMINAL_BRIDGE_ERROR"})
        except WebSocketDisconnect:
            pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await terminal.close()
