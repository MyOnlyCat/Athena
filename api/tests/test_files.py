from typing import Any

import asyncssh
import pytest

from app.services.files import AsyncRemoteFiles
from app.services.ssh import HostConnection
from tests.test_terminal import auth_headers, create_trusted_host


class FakeRemoteFiles:
    def __init__(self) -> None:
        self.directories: list[str] = []
        self.renames: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, bool]] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.connections: list[HostConnection] = []

    async def list(self, connection, path):
        self.connections.append(connection)
        return [
            {
                "name": "release",
                "path": f"{path.rstrip('/')}/release",
                "type": "directory",
                "size": 0,
                "modified_at": None,
                "permissions": "drwxr-xr-x",
            }
        ]

    async def mkdir(self, connection, path):
        self.directories.append(path)

    async def rename(self, connection, source, destination):
        self.renames.append((source, destination))

    async def delete(self, connection, path, recursive):
        self.deletes.append((path, recursive))

    async def upload(self, connection, path, chunks):
        content = b""
        async for chunk in chunks:
            content += chunk
        self.uploads.append((path, content))

    async def download(self, connection, path):
        yield b"artifact-"
        yield b"content"


class FakeRemoteFile:
    def __init__(self) -> None:
        self.chunks = iter([b"artifact-", b"content", b""])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def read(self, size):
        return next(self.chunks)


class FakeSFTP:
    def __init__(self) -> None:
        self.exited = False
        self.remote = FakeRemoteFile()

    def open(self, path, mode):
        return self.remote

    def exit(self):
        self.exited = True


class FakeSSH:
    def __init__(self) -> None:
        self.closed = False
        self.waited_for_close = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        self.waited_for_close = True


class DownloadRemoteFiles(AsyncRemoteFiles):
    def __init__(self, ssh, sftp) -> None:
        self.ssh = ssh
        self.sftp = sftp

    async def _connect(self, connection):
        return self.ssh, self.sftp


def test_remote_files_can_be_listed_and_mutated(client):
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)
    fake = FakeRemoteFiles()
    client.app.state.remote_files = fake

    listing = client.get(
        f"/api/v1/files/{host['id']}/list",
        headers=headers,
        params={"path": "/opt"},
    )
    assert listing.status_code == 200
    assert listing.json()["entries"][0]["path"] == "/opt/release"

    assert client.post(
        f"/api/v1/files/{host['id']}/directories",
        headers=headers,
        json={"path": "/opt/new"},
    ).status_code == 204
    assert client.patch(
        f"/api/v1/files/{host['id']}/rename",
        headers=headers,
        json={"source": "/opt/new", "destination": "/opt/current"},
    ).status_code == 204
    assert client.request(
        "DELETE",
        f"/api/v1/files/{host['id']}",
        headers=headers,
        json={"path": "/opt/current", "recursive": True},
    ).status_code == 204

    assert fake.directories == ["/opt/new"]
    assert fake.renames == [("/opt/new", "/opt/current")]
    assert fake.deletes == [("/opt/current", True)]
    assert fake.connections[0].host_key_fingerprint == "SHA256:trusted"


def test_remote_file_can_be_uploaded_and_downloaded(client):
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)
    fake = FakeRemoteFiles()
    client.app.state.remote_files = fake

    uploaded = client.post(
        f"/api/v1/files/{host['id']}/upload",
        headers={**headers, "Content-Type": "application/octet-stream"},
        params={"path": "/opt/release/app.jar"},
        content=b"artifact-content",
    )
    assert uploaded.status_code == 204
    assert fake.uploads == [("/opt/release/app.jar", b"artifact-content")]

    downloaded = client.get(
        f"/api/v1/files/{host['id']}/download",
        headers=headers,
        params={"path": '/opt/release/\u6d4b\u8bd5"unsafe\r\n.txt'},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"artifact-content"
    content_disposition = downloaded.headers["content-disposition"]
    assert 'filename="unsafe.txt"; filename*=' in content_disposition
    assert "filename*=UTF-8''%E6%B5%8B%E8%AF%95%22unsafe%0D%0A.txt" in content_disposition
    assert "\r" not in content_disposition
    assert "\n" not in content_disposition


async def test_download_streaming_closes_the_sftp_connection_after_consumption():
    ssh = FakeSSH()
    sftp = FakeSFTP()
    remote_files = DownloadRemoteFiles(ssh, sftp)
    connection = HostConnection("127.0.0.1", 22, "deploy", "secret")

    chunks = [chunk async for chunk in remote_files.download(connection, "/opt/release/app.jar")]

    assert b"".join(chunks) == b"artifact-content"
    assert sftp.exited
    assert ssh.closed
    assert ssh.waited_for_close


async def test_download_streaming_closes_after_consumer_aclose():
    ssh = FakeSSH()
    sftp = FakeSFTP()
    remote_files = DownloadRemoteFiles(ssh, sftp)
    connection = HostConnection(
        "127.0.0.1",
        22,
        "deploy",
        "secret",
        host_key_fingerprint="SHA256:trusted",
    )
    stream = remote_files.download(connection, "/opt/release/app.jar")

    assert await anext(stream) == b"artifact-"
    await stream.aclose()

    assert sftp.exited
    assert ssh.closed
    assert ssh.waited_for_close


class ReadFailingRemoteFile(FakeRemoteFile):
    async def read(self, size: int) -> bytes:
        del size
        raise OSError("remote read failed")


async def test_download_streaming_closes_when_remote_read_raises():
    ssh = FakeSSH()
    sftp = FakeSFTP()
    sftp.remote = ReadFailingRemoteFile()
    remote_files = DownloadRemoteFiles(ssh, sftp)
    connection = HostConnection(
        "127.0.0.1",
        22,
        "deploy",
        "secret",
        host_key_fingerprint="SHA256:trusted",
    )

    with pytest.raises(OSError, match="remote read failed"):
        await anext(remote_files.download(connection, "/opt/release/app.jar"))

    assert sftp.exited
    assert ssh.closed
    assert ssh.waited_for_close


class FailingSFTPConnection(FakeSSH):
    async def start_sftp_client(self) -> None:
        raise asyncssh.ChannelOpenError(1, "SFTP unavailable")


@pytest.mark.asyncio
async def test_sftp_acquisition_failure_closes_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssh = FailingSFTPConnection()

    async def connect(*args: Any, **kwargs: Any) -> FailingSFTPConnection:
        del args, kwargs
        return ssh

    import app.services.files as files_module

    monkeypatch.setattr(files_module, "connect_ssh", connect, raising=False)

    with pytest.raises(asyncssh.ChannelOpenError):
        await AsyncRemoteFiles()._connect(
            HostConnection(
                "node.example.com",
                22,
                "root",
                "secret",
                host_key_fingerprint="SHA256:trusted",
            )
        )

    assert ssh.closed
    assert ssh.waited_for_close


def test_file_path_rejects_null_bytes(client):
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)
    response = client.post(
        f"/api/v1/files/{host['id']}/directories",
        headers=headers,
        json={"path": "/opt/bad\u0000path"},
    )
    assert response.status_code == 422
