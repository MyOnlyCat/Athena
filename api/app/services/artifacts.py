import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx

from app.core.errors import AppError


class ArtifactService:
    def __init__(
        self,
        http: httpx.AsyncClient,
        root: Path,
        *,
        allow_http: bool = False,
        max_bytes: int = 10 * 1024 * 1024 * 1024,
    ) -> None:
        self.http = http
        self.root = root
        self.allow_http = allow_http
        self.max_bytes = max_bytes

    async def download(
        self,
        *,
        task_id: str,
        url: str,
        filename: str,
        expected_sha256: str,
        progress: Callable[[int], None] | None = None,
    ) -> Path:
        if not url.startswith("https://") and not self.allow_http:
            raise AppError(
                "ARTIFACT_HTTPS_REQUIRED",
                "制品下载地址必须使用 HTTPS",
                status_code=422,
            )
        task_dir = self.root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        partial = task_dir / f"{filename}.part"
        final = task_dir / filename
        digest = hashlib.sha256()
        received = 0
        try:
            async with self.http.stream("GET", url) as response:
                response.raise_for_status()
                expected_size = int(response.headers.get("Content-Length", "0"))
                with partial.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > self.max_bytes:
                            raise AppError(
                                "ARTIFACT_TOO_LARGE",
                                "制品超过大小限制",
                                status_code=413,
                            )
                        digest.update(chunk)
                        output.write(chunk)
                        if progress and expected_size:
                            progress(min(99, int(received * 100 / expected_size)))
            if digest.hexdigest() != expected_sha256:
                raise AppError(
                    "ARTIFACT_CHECKSUM_MISMATCH",
                    "制品 SHA-256 校验失败",
                    status_code=422,
                )
            partial.replace(final)
            if progress:
                progress(100)
            return final
        except Exception:
            partial.unlink(missing_ok=True)
            raise

