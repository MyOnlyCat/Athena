from tests.test_terminal import auth_headers, create_trusted_host


class FakeRemoteFiles:
    def __init__(self) -> None:
        self.directories: list[str] = []
        self.renames: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, bool]] = []
        self.uploads: list[tuple[str, bytes]] = []

    async def list(self, connection, path):
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
        yield b"artifact-content"


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
        params={"path": "/opt/release/app.jar"},
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"artifact-content"
    assert downloaded.headers["content-disposition"] == 'attachment; filename="app.jar"'


def test_file_path_rejects_null_bytes(client):
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)
    response = client.post(
        f"/api/v1/files/{host['id']}/directories",
        headers=headers,
        json={"path": "/opt/bad\u0000path"},
    )
    assert response.status_code == 422
