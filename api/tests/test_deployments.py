from sqlalchemy import func, select

from app.models.deployment import DeploymentTarget, DeploymentTask
from app.schemas.deployment import ClaimedTask
from app.services.deployments import DeploymentCoordinator


def claimed_task() -> ClaimedTask:
    return ClaimedTask.model_validate(
        {
            "task_id": "release-1",
            "artifact": {
                "url": "https://artifacts.example/app.jar",
                "sha256": "a" * 64,
                "name": "app.jar",
            },
            "targets": [
                {
                    "ip": "10.0.0.10",
                    "directory": "/opt/apps/example",
                    "command": "systemctl restart example",
                }
            ],
        }
    )


async def test_duplicate_master_task_is_stored_once(db_session):
    coordinator = DeploymentCoordinator(db_session)

    first = await coordinator.accept_claim(claimed_task())
    second = await coordinator.accept_claim(claimed_task())

    assert first.id == second.id
    assert await db_session.scalar(select(func.count()).select_from(DeploymentTask)) == 1
    assert await db_session.scalar(select(func.count()).select_from(DeploymentTarget)) == 1


async def test_executing_target_becomes_manual_review_after_restart(db_session):
    coordinator = DeploymentCoordinator(db_session)
    task = await coordinator.accept_claim(claimed_task())
    target = task.targets[0]
    target.status = "executing"
    await db_session.commit()

    recovered = await coordinator.recover_interrupted()

    assert recovered == 1
    assert target.status == "manual_review"
    assert task.status == "manual_review"

