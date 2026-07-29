from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.deployment import DeploymentTarget, DeploymentTask
from app.schemas.deployment import ClaimedTask


class DeploymentCoordinator:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def accept_claim(self, claim: ClaimedTask) -> DeploymentTask:
        existing = await self.session.scalar(
            select(DeploymentTask)
            .options(selectinload(DeploymentTask.targets))
            .where(DeploymentTask.master_task_id == claim.task_id)
        )
        if existing is not None:
            return existing
        task = DeploymentTask(
            master_task_id=claim.task_id,
            artifact_url=claim.artifact.url,
            artifact_sha256=claim.artifact.sha256,
            artifact_name=claim.artifact.name,
            targets=[
                DeploymentTarget(
                    target_ip=target.ip,
                    target_directory=target.directory,
                    command=target.command,
                )
                for target in claim.targets
            ],
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def recover_interrupted(self) -> int:
        targets = list(
            (
                await self.session.scalars(
                    select(DeploymentTarget)
                    .options(selectinload(DeploymentTarget.task))
                    .where(DeploymentTarget.status == "executing")
                )
            ).all()
        )
        for target in targets:
            target.status = "manual_review"
            target.finished_at = datetime.now(UTC)
            target.task.status = "manual_review"
            target.task.finished_at = datetime.now(UTC)
        await self.session.commit()
        return len(targets)

    async def list_tasks(self) -> list[DeploymentTask]:
        return list(
            (
                await self.session.scalars(
                    select(DeploymentTask)
                    .options(selectinload(DeploymentTask.targets))
                    .order_by(DeploymentTask.claimed_at.desc())
                )
            ).all()
        )

    async def get_task(self, task_id: str) -> DeploymentTask | None:
        return cast(
            DeploymentTask | None,
            await self.session.scalar(
                select(DeploymentTask)
                .options(selectinload(DeploymentTask.targets))
                .where(DeploymentTask.id == task_id)
            ),
        )
