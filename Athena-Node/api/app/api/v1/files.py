import posixpath
from collections.abc import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response, status
from starlette.responses import StreamingResponse

from app.api.deps import CurrentUserDep, SessionDep
from app.core.errors import AppError
from app.models.host import Host
from app.schemas.file import (
    DirectoryCreate,
    FileDelete,
    FileListResponse,
    FileRename,
    validate_remote_path,
)
from app.services.crypto import CredentialCipher
from app.services.ssh import HostConnection

router = APIRouter(prefix="/files", tags=["files"])


async def connection_for(request: Request, session: SessionDep, host_id: str) -> HostConnection:
    host = await session.get(Host, host_id)
    if host is None:
        raise AppError("HOST_NOT_FOUND", "主机不存在", status_code=404)
    if not host.host_key_fingerprint:
        raise AppError("SSH_HOST_UNTRUSTED", "请先确认 SSH 主机指纹", status_code=409)
    password = CredentialCipher(request.app.state.settings.credential_key).decrypt(
        host.encrypted_password
    )
    return HostConnection(
        host.address,
        host.port,
        host.username,
        password,
        host.host_key_fingerprint,
    )


@router.get("/{host_id}/list", response_model=FileListResponse)
async def list_files(
    host_id: str,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
    path: str = Query("/"),
) -> FileListResponse:
    path = validate_remote_path(path)
    connection = await connection_for(request, session, host_id)
    entries = await request.app.state.remote_files.list(connection, path)
    return FileListResponse(path=path, entries=entries)


@router.post("/{host_id}/directories", status_code=status.HTTP_204_NO_CONTENT)
async def create_directory(
    host_id: str,
    data: DirectoryCreate,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Response:
    connection = await connection_for(request, session, host_id)
    await request.app.state.remote_files.mkdir(connection, data.path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{host_id}/rename", status_code=status.HTTP_204_NO_CONTENT)
async def rename_file(
    host_id: str,
    data: FileRename,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Response:
    connection = await connection_for(request, session, host_id)
    await request.app.state.remote_files.rename(connection, data.source, data.destination)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    host_id: str,
    data: FileDelete,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Response:
    connection = await connection_for(request, session, host_id)
    await request.app.state.remote_files.delete(connection, data.path, data.recursive)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{host_id}/upload", status_code=status.HTTP_204_NO_CONTENT)
async def upload_file(
    host_id: str,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
    path: str = Query(...),
) -> Response:
    path = validate_remote_path(path)
    connection = await connection_for(request, session, host_id)

    async def limited_chunks() -> AsyncIterator[bytes]:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > request.app.state.settings.max_upload_bytes:
                raise AppError("FILE_TOO_LARGE", "上传文件超过大小限制", status_code=413)
            yield chunk

    await request.app.state.remote_files.upload(connection, path, limited_chunks())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{host_id}/download")
async def download_file(
    host_id: str,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
    path: str = Query(...),
) -> StreamingResponse:
    path = validate_remote_path(path)
    connection = await connection_for(request, session, host_id)
    filename = posixpath.basename(path)
    fallback_filename = filename.encode("ascii", "ignore").decode("ascii")
    fallback_filename = fallback_filename.replace("\\", "_").replace('"', "")
    fallback_filename = fallback_filename.replace("\r", "").replace("\n", "") or "download"
    content_disposition = (
        f'attachment; filename="{fallback_filename}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return StreamingResponse(
        request.app.state.remote_files.download(connection, path),
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition},
    )
