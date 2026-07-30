import posixpath
import stat
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.services.ssh import HostConnection, connect_ssh


class AsyncRemoteFiles:
    async def _connect(self, connection: HostConnection) -> tuple[Any, Any]:
        ssh = await connect_ssh(connection)
        try:
            return ssh, await ssh.start_sftp_client()
        except BaseException as exc:
            try:
                ssh.close()
            except BaseException as close_error:
                exc.add_note(f"SSH close failed: {close_error!r}")
            try:
                await ssh.wait_closed()
            except BaseException as wait_error:
                exc.add_note(f"SSH wait_closed failed: {wait_error!r}")
            raise

    async def list(self, connection: HostConnection, path: str) -> list[dict[str, Any]]:
        ssh, sftp = await self._connect(connection)
        try:
            entries = []
            async for item in sftp.scandir(path):
                attrs = item.attrs
                permissions = attrs.permissions or 0
                entries.append(
                    {
                        "name": item.filename,
                        "path": posixpath.join(path, item.filename),
                        "type": "directory" if stat.S_ISDIR(permissions) else "file",
                        "size": attrs.size or 0,
                        "modified_at": (
                            datetime.fromtimestamp(attrs.mtime, UTC) if attrs.mtime else None
                        ),
                        "permissions": stat.filemode(permissions),
                    }
                )
            return entries
        finally:
            sftp.exit()
            ssh.close()
            await ssh.wait_closed()

    async def mkdir(self, connection: HostConnection, path: str) -> None:
        ssh, sftp = await self._connect(connection)
        try:
            await sftp.mkdir(path)
        finally:
            sftp.exit()
            ssh.close()
            await ssh.wait_closed()

    async def rename(self, connection: HostConnection, source: str, destination: str) -> None:
        ssh, sftp = await self._connect(connection)
        try:
            await sftp.rename(source, destination)
        finally:
            sftp.exit()
            ssh.close()
            await ssh.wait_closed()

    async def delete(self, connection: HostConnection, path: str, recursive: bool) -> None:
        ssh, sftp = await self._connect(connection)
        try:
            attrs = await sftp.stat(path)
            if stat.S_ISDIR(attrs.permissions or 0):
                if recursive:
                    await sftp.rmtree(path)
                else:
                    await sftp.rmdir(path)
            else:
                await sftp.remove(path)
        finally:
            sftp.exit()
            ssh.close()
            await ssh.wait_closed()

    async def upload(
        self,
        connection: HostConnection,
        path: str,
        chunks: AsyncIterator[bytes],
    ) -> None:
        ssh, sftp = await self._connect(connection)
        try:
            async with sftp.open(path, "wb") as remote:
                async for chunk in chunks:
                    await remote.write(chunk)
        finally:
            sftp.exit()
            ssh.close()
            await ssh.wait_closed()

    async def download(
        self,
        connection: HostConnection,
        path: str,
    ) -> AsyncIterator[bytes]:
        ssh, sftp = await self._connect(connection)
        try:
            async with sftp.open(path, "rb") as remote:
                while chunk := await remote.read(64 * 1024):
                    yield chunk
        finally:
            sftp.exit()
            ssh.close()
            await ssh.wait_closed()
