from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUserDep, SessionDep
from app.core.errors import AppError
from app.models.deployment import DeploymentEvent, DeploymentTask
from app.schemas.task import EventResponse, TaskResponse
from app.services.deployments import DeploymentCoordinator

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskResponse])
async def list_tasks(session: SessionDep, _: CurrentUserDep) -> list[DeploymentTask]:
    return await DeploymentCoordinator(session).list_tasks()


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    session: SessionDep,
    _: CurrentUserDep,
) -> DeploymentTask:
    task = await DeploymentCoordinator(session).get_task(task_id)
    if task is None:
        raise AppError("TASK_NOT_FOUND", "发布任务不存在", status_code=404)
    return task


@router.get("/{task_id}/events", response_model=list[EventResponse])
async def list_events(
    task_id: str,
    session: SessionDep,
    _: CurrentUserDep,
) -> list[DeploymentEvent]:
    task = await DeploymentCoordinator(session).get_task(task_id)
    if task is None:
        raise AppError("TASK_NOT_FOUND", "发布任务不存在", status_code=404)
    return list(
        (
            await session.scalars(
                select(DeploymentEvent)
                .where(DeploymentEvent.task_id == task.master_task_id)
                .order_by(DeploymentEvent.sequence)
            )
        ).all()
    )

