from dataclasses import dataclass
from typing import Any, Protocol

import asyncssh


@dataclass(frozen=True)
class HostConnection:
    address: str
    port: int
    username: str
    password: str


class SSHClientProtocol(Protocol):
    async def test_connection(self, connection: HostConnection) -> dict[str, Any]: ...


class AsyncSSHClient:
    async def test_connection(self, connection: HostConnection) -> dict[str, Any]:
        async with asyncssh.connect(
            connection.address,
            port=connection.port,
            username=connection.username,
            password=connection.password,
            known_hosts=None,
            connect_timeout=10,
        ) as client:
            key = client.get_server_host_key()
            if key is None:
                raise OSError("SSH server did not provide a host key")
            return {
                "status": "connected",
                "code": "SSH_CONNECTED",
                "message": "SSH 连接成功",
                "fingerprint": key.get_fingerprint("sha256"),
            }
