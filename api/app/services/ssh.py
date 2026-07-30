from dataclasses import dataclass
from hmac import compare_digest
from typing import Any, Protocol

import asyncssh

_CLIENT_VALIDATED_KNOWN_HOSTS = (
    b"# Host keys are validated by PinnedSSHClient.validate_host_public_key\n"
)


@dataclass(frozen=True)
class HostConnection:
    address: str
    port: int
    username: str
    password: str
    host_key_fingerprint: str | None = None


class SSHHostKeyUntrusted(asyncssh.HostKeyNotVerifiable):
    """Raised when a non-TOFU SSH boundary has no saved host-key pin."""


class SSHHostKeyChanged(asyncssh.HostKeyNotVerifiable):
    """Raised when the server key differs from the saved SHA-256 pin."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__("SSH server host key does not match the saved fingerprint")
        self.expected = expected
        self.actual = actual


class PinnedSSHClient(asyncssh.SSHClient):
    """Validate the server key during key exchange, before authentication."""

    def __init__(self, expected_fingerprint: str | None) -> None:
        self.expected_fingerprint = expected_fingerprint
        self.presented_fingerprint: str | None = None

    def validate_host_public_key(
        self,
        host: str,
        addr: str,
        port: int,
        key: asyncssh.SSHKey,
    ) -> bool:
        del host, addr, port
        fingerprint = key.get_fingerprint("sha256")
        self.presented_fingerprint = fingerprint
        expected = self.expected_fingerprint
        return expected is None or compare_digest(fingerprint, expected)


async def connect_ssh(
    connection: HostConnection,
    *,
    allow_tofu: bool = False,
    connect_timeout: float | None = None,
) -> asyncssh.SSHClientConnection:
    """Open SSH with application-owned host-key validation."""

    expected = connection.host_key_fingerprint
    if expected is None and not allow_tofu:
        raise SSHHostKeyUntrusted("SSH host fingerprint has not been trusted")

    validator = PinnedSSHClient(expected)
    options: dict[str, Any] = {
        "port": connection.port,
        "username": connection.username,
        "password": connection.password,
        "known_hosts": _CLIENT_VALIDATED_KNOWN_HOSTS,
        "client_factory": lambda: validator,
        "server_host_key_algs": "default",
    }
    if connect_timeout is not None:
        options["connect_timeout"] = connect_timeout

    try:
        return await asyncssh.connect(connection.address, **options)
    except asyncssh.HostKeyNotVerifiable as exc:
        actual = validator.presented_fingerprint
        if expected is not None and actual is not None and not compare_digest(actual, expected):
            raise SSHHostKeyChanged(expected, actual) from exc
        raise


class SSHClientProtocol(Protocol):
    async def test_connection(self, connection: HostConnection) -> dict[str, Any]: ...


class AsyncSSHClient:
    async def test_connection(self, connection: HostConnection) -> dict[str, Any]:
        client = await connect_ssh(
            connection,
            allow_tofu=True,
            connect_timeout=10,
        )
        try:
            key = client.get_server_host_key()
            if key is None:
                raise OSError("SSH server did not provide a host key")
            return {
                "status": "connected",
                "code": "SSH_CONNECTED",
                "message": "SSH 连接成功",
                "fingerprint": key.get_fingerprint("sha256"),
            }
        finally:
            client.close()
            await client.wait_closed()
