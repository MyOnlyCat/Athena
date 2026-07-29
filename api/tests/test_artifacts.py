import hashlib

import httpx
import pytest

from app.core.errors import AppError
from app.services.artifacts import ArtifactService


@pytest.mark.asyncio
async def test_artifact_is_streamed_and_sha256_verified(tmp_path):
    content = b"athena-artifact"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    async with httpx.AsyncClient(transport=transport) as http:
        service = ArtifactService(http, tmp_path)
        path = await service.download(
            task_id="task-1",
            url="https://artifacts.example/app.jar",
            filename="app.jar",
            expected_sha256=hashlib.sha256(content).hexdigest(),
        )

    assert path.read_bytes() == content
    assert path.name == "app.jar"


@pytest.mark.asyncio
async def test_artifact_checksum_mismatch_removes_download(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad"))
    async with httpx.AsyncClient(transport=transport) as http:
        service = ArtifactService(http, tmp_path)
        with pytest.raises(AppError) as error:
            await service.download(
                task_id="task-1",
                url="https://artifacts.example/app.jar",
                filename="app.jar",
                expected_sha256="0" * 64,
            )

    assert error.value.code == "ARTIFACT_CHECKSUM_MISMATCH"
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.asyncio
async def test_plain_http_artifact_is_rejected(tmp_path):
    async with httpx.AsyncClient() as http:
        with pytest.raises(AppError) as error:
            await ArtifactService(http, tmp_path).download(
                task_id="task-1",
                url="http://artifacts.example/app.jar",
                filename="app.jar",
                expected_sha256="0" * 64,
            )
    assert error.value.code == "ARTIFACT_HTTPS_REQUIRED"

