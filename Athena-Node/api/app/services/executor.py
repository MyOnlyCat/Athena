import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.deployment import DeploymentTarget, DeploymentTask
from app.models.host import Host
from app.schemas.deployment import ClaimedTask
from app.services.crypto import CredentialCipher
from app.services.deployments import DeploymentCoordinator
from app.services.events import EventService
from app.services.ssh import HostConnection


class DeploymentExecutor:
    def __init__(
        self,
        *,
        session_factory: Any,
        master_client: Any,
        artifact_service: Any,
        gateway: Any,
        cipher: CredentialCipher,
        concurrency: int = 4,
    ) -> None:
        self.session_factory = session_factory
        self.master_client = master_client
        self.artifact_service = artifact_service
        self.gateway = gateway
        self.cipher = cipher
        self.semaphore = asyncio.Semaphore(concurrency)
        self.host_locks: dict[str, asyncio.Lock] = {}
        self.running: set[asyncio.Task[None]] = set()

    async def recover(self) -> int:
        async with self.session_factory() as session:
            return await DeploymentCoordinator(session).recover_interrupted()

    async def poll(self) -> None:
        if self.master_client is None:
            return
        claims = await self.master_client.claim_tasks(len(self.running))
        for raw in claims:
            claim = ClaimedTask.model_validate(raw)
            async with self.session_factory() as session:
                task = await DeploymentCoordinator(session).accept_claim(claim)
                task_id = task.id
                is_new = task.status == "claimed" and task.started_at is None
            if is_new and all(item.get_name() != task_id for item in self.running):
                runner = asyncio.create_task(self.execute(task_id), name=task_id)
                self.running.add(runner)
                runner.add_done_callback(self.running.discard)

    async def execute(self, task_id: str) -> None:
        async with self.session_factory() as session:
            task = await session.scalar(
                select(DeploymentTask)
                .options(selectinload(DeploymentTask.targets))
                .where(DeploymentTask.id == task_id)
            )
            if task is None:
                return
            task.status = "downloading"
            task.started_at = datetime.now(UTC)
            await session.commit()
            events = EventService(session, self.master_client)
            await events.append(task.master_task_id, None, "stage", {"stage": "downloading"})
            try:
                artifact = await self.artifact_service.download(
                    task_id=task.master_task_id,
                    url=task.artifact_url,
                    filename=task.artifact_name,
                    expected_sha256=task.artifact_sha256,
                )
                task.status = "running"
                await session.commit()
                await events.append(task.master_task_id, None, "stage", {"stage": "running"})
                await asyncio.gather(
                    *[
                        self._execute_target(task, target, artifact, events)
                        for target in task.targets
                    ]
                )
                task.status = (
                    "succeeded"
                    if all(target.status == "succeeded" for target in task.targets)
                    else "failed"
                )
            except Exception as exc:
                task.status = "failed"
                task.error_code = "DEPLOYMENT_FAILED"
                task.error_message = str(exc)[:1000]
            task.finished_at = datetime.now(UTC)
            await session.commit()
            await events.append(
                task.master_task_id,
                None,
                "result",
                {"status": task.status, "message": task.error_message},
            )
            await events.deliver_pending(task.master_task_id)

    async def _execute_target(
        self,
        task: DeploymentTask,
        target: DeploymentTarget,
        artifact: Any,
        events: EventService,
    ) -> None:
        async with self.semaphore, self.host_locks.setdefault(target.target_ip, asyncio.Lock()):
            host = await events.session.scalar(
                select(Host).where(Host.address == target.target_ip)
            )
            if host is None:
                target.status = "failed"
                await events.append(
                    task.master_task_id,
                    target.id,
                    "result",
                    {"status": "failed", "code": "TARGET_HOST_NOT_FOUND"},
                )
                return
            target.host_id = host.id
            target.status = "executing"
            target.started_at = datetime.now(UTC)
            await events.session.commit()

            async def output(event_type: str, data: str) -> None:
                await events.append(
                    task.master_task_id,
                    target.id,
                    event_type,
                    {"data": data[:16_000]},
                )
                await events.deliver_pending(task.master_task_id)

            exit_code = await self.gateway.deploy(
                HostConnection(
                    host.address,
                    host.port,
                    host.username,
                    self.cipher.decrypt(host.encrypted_password),
                    host.host_key_fingerprint,
                ),
                artifact,
                target.target_directory,
                task.artifact_name,
                target.command,
                output,
            )
            target.exit_code = exit_code
            target.progress = 100
            target.status = "succeeded" if exit_code == 0 else "failed"
            target.finished_at = datetime.now(UTC)
            await events.session.commit()
            await events.append(
                task.master_task_id,
                target.id,
                "result",
                {"status": target.status, "exit_code": exit_code},
            )

    async def close(self) -> None:
        if self.running:
            await asyncio.gather(*self.running, return_exceptions=True)
