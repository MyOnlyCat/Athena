from pathlib import Path
from types import SimpleNamespace
from typing import Any

import asyncssh
import pytest
from sqlalchemy import func, select

from app.models.deployment import DeploymentTarget, DeploymentTask
from app.models.host import Host
from app.schemas.deployment import ClaimedTask
from app.services.crypto import CredentialCipher
from app.services.deployment_gateway import AsyncDeploymentGateway
from app.services.deployments import DeploymentCoordinator
from app.services.executor import DeploymentExecutor
from app.services.ssh import HostConnection


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


class FakeGatewaySession:
    def __init__(self, host: Host) -> None:
        self.host = host
        self.commits = 0

    async def scalar(self, query: Any) -> Host:
        del query
        return self.host

    async def commit(self) -> None:
        self.commits += 1


class FakeGatewayEvents:
    def __init__(self, host: Host) -> None:
        self.session = FakeGatewaySession(host)

    async def append(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def deliver_pending(self, task_id: str) -> None:
        del task_id


class CapturingDeploymentGateway:
    def __init__(self) -> None:
        self.connection: HostConnection | None = None

    async def deploy(
        self,
        connection: HostConnection,
        *args: Any,
        **kwargs: Any,
    ) -> int:
        del args, kwargs
        self.connection = connection
        return 0


@pytest.mark.asyncio
async def test_deployment_executor_passes_saved_host_key_pin() -> None:
    cipher = CredentialCipher("4UlSOndzr4KYLmDMK5T5OmRsWLOtqzmNe01_sucGm2o=")
    host = Host(
        name="deploy-host",
        address="10.0.0.10",
        port=22,
        username="root",
        encrypted_password=cipher.encrypt("secret"),
        tags=[],
        is_local=False,
        host_key_fingerprint="SHA256:trusted",
    )
    target = SimpleNamespace(
        target_ip=host.address,
        id="target-1",
        target_directory="/opt/app",
        command="true",
        status="claimed",
        started_at=None,
        host_id=None,
        exit_code=None,
        progress=0,
        finished_at=None,
    )
    task = SimpleNamespace(master_task_id="task-1", artifact_name="app.jar")
    gateway = CapturingDeploymentGateway()
    executor = DeploymentExecutor(
        session_factory=None,
        master_client=None,
        artifact_service=None,
        gateway=gateway,
        cipher=cipher,
    )

    await executor._execute_target(
        task,
        target,
        Path("app.jar"),
        FakeGatewayEvents(host),
    )

    assert gateway.connection is not None
    assert gateway.connection.host_key_fingerprint == "SHA256:trusted"


@pytest.mark.asyncio
async def test_deployment_gateway_rejects_changed_key_before_sftp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = HostConnection(
        "node.example.com",
        22,
        "root",
        "secret",
        host_key_fingerprint="SHA256:trusted",
    )

    async def pinned_connect(
        received: HostConnection,
        **kwargs: Any,
    ) -> None:
        del kwargs
        assert received.host_key_fingerprint == "SHA256:trusted"
        raise asyncssh.HostKeyNotVerifiable("Host key is not trusted")

    import app.services.deployment_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "connect_ssh", pinned_connect, raising=False)

    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        await AsyncDeploymentGateway().deploy(
            connection,
            Path("app.jar"),
            "/opt/app",
            "app.jar",
            "true",
            lambda event_type, data: None,  # type: ignore[arg-type]
        )
