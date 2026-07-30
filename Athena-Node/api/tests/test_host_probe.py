import asyncio

import pytest

from app.core.database import Base, create_engine, create_session_factory
from app.models.host import Host
from app.services.crypto import CredentialCipher
from app.services.host_probe import HostProbeScheduler
from app.services.ssh import HostConnection


class RecordingProbeScheduler(HostProbeScheduler):
    def __init__(self) -> None:
        super().__init__(
            session_factory=None,  # type: ignore[arg-type]
            cipher=None,  # type: ignore[arg-type]
            ssh_client=None,  # type: ignore[arg-type]
        )
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Queue[None]()
        self.release = asyncio.Queue[None]()

    async def interval_minutes(self) -> int:
        return 1440

    async def probe_all(self) -> None:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await self.started.put(None)
        await self.release.get()
        self.active -= 1


@pytest.mark.asyncio
async def test_scheduler_probes_immediately_and_reschedules_without_overlap() -> None:
    scheduler = RecordingProbeScheduler()
    scheduler.start()

    await asyncio.wait_for(scheduler.started.get(), timeout=1)
    scheduler.reschedule()
    await scheduler.release.put(None)
    await asyncio.wait_for(scheduler.started.get(), timeout=1)

    assert scheduler.calls == 2
    assert scheduler.max_active == 1

    await scheduler.release.put(None)
    await scheduler.stop()


class BlockingSSHClient:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Queue[None]()
        self.release = asyncio.Queue[None]()

    async def test_connection(self, connection: HostConnection) -> dict[str, object]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await self.started.put(None)
        await self.release.get()
        self.active -= 1
        return {
            "status": "success",
            "code": "SSH_CONNECTED",
            "message": "SSH 连接成功",
            "fingerprint": connection.host_key_fingerprint,
        }


@pytest.mark.asyncio
async def test_probe_round_limits_host_concurrency_to_five(settings) -> None:
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    cipher = CredentialCipher(settings.credential_key)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add_all(
            Host(
                name=f"host-{index}",
                address=f"192.0.2.{index}",
                port=22,
                username="root",
                encrypted_password=cipher.encrypt("secret"),
                tags=[],
                is_local=False,
                host_key_fingerprint="SHA256:trusted",
            )
            for index in range(1, 8)
        )
        await session.commit()

    ssh = BlockingSSHClient()
    scheduler = HostProbeScheduler(factory, cipher, ssh, concurrency=5)
    round_task = asyncio.create_task(scheduler.probe_all())

    for _ in range(5):
        await asyncio.wait_for(ssh.started.get(), timeout=1)
    assert ssh.max_active == 5
    assert ssh.started.empty()

    for _ in range(5):
        await ssh.release.put(None)
    for _ in range(2):
        await asyncio.wait_for(ssh.started.get(), timeout=1)
        await ssh.release.put(None)

    await asyncio.wait_for(round_task, timeout=1)
    assert ssh.max_active == 5
    await engine.dispose()
