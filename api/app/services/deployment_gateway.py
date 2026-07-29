import asyncio
import posixpath
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path
from secrets import token_hex
from typing import Any

import asyncssh

from app.services.ssh import HostConnection

OutputCallback = Callable[[str, str], Awaitable[None]]


class AsyncDeploymentGateway:
    async def deploy(
        self,
        connection: HostConnection,
        local_artifact: Path,
        directory: str,
        artifact_name: str,
        command: str,
        output: OutputCallback,
    ) -> int:
        ssh = await asyncssh.connect(
            connection.address,
            port=connection.port,
            username=connection.username,
            password=connection.password,
            known_hosts=None,
        )
        try:
            sftp = await ssh.start_sftp_client()
            await sftp.makedirs(directory, exist_ok=True)
            temporary = posixpath.join(directory, f".{artifact_name}.{token_hex(8)}.part")
            destination = posixpath.join(directory, artifact_name)
            await sftp.put(str(local_artifact), temporary)
            await sftp.rename(temporary, destination)
            remote_command = f"cd -- {shlex.quote(directory)} && {command}"
            process = await ssh.create_process(remote_command, encoding="utf-8")

            async def stream(reader: Any, event_type: str) -> None:
                async for line in reader:
                    await output(event_type, str(line))

            await asyncio.gather(
                stream(process.stdout, "stdout"),
                stream(process.stderr, "stderr"),
            )
            completed = await process.wait()
            return completed.exit_status if completed.exit_status is not None else 255
        finally:
            ssh.close()
            await ssh.wait_closed()
