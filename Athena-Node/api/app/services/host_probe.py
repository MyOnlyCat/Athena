import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.host import Host
from app.models.host_probe_setting import HostProbeSetting
from app.services.crypto import CredentialCipher
from app.services.hosts import HostService
from app.services.ssh import SSHClientProtocol

logger = logging.getLogger(__name__)


class HostProbeSettingsService:
    def __init__(self, session: AsyncSession, default_interval_minutes: int = 5) -> None:
        self.session = session
        self.default_interval_minutes = default_interval_minutes

    async def get(self) -> HostProbeSetting:
        setting = await self.session.get(HostProbeSetting, 1)
        if setting is None:
            setting = HostProbeSetting(
                id=1,
                interval_minutes=self.default_interval_minutes,
            )
            self.session.add(setting)
            await self.session.commit()
            await self.session.refresh(setting)
        return setting

    async def update(self, interval_minutes: int) -> HostProbeSetting:
        setting = await self.get()
        setting.interval_minutes = interval_minutes
        await self.session.commit()
        await self.session.refresh(setting)
        return setting


class HostProbeScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cipher: CredentialCipher,
        ssh_client: SSHClientProtocol,
        *,
        default_interval_minutes: int = 5,
        concurrency: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.cipher = cipher
        self.ssh_client = ssh_client
        self.default_interval_minutes = default_interval_minutes
        self.concurrency = concurrency
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="host-probe-scheduler")

    async def stop(self) -> None:
        self._stopping = True
        self._wakeup.set()
        if self._task is not None:
            await self._task
        self._task = None

    def reschedule(self) -> None:
        """Run a fresh probe as soon as the current non-overlapping round finishes."""
        self._wakeup.set()

    async def interval_minutes(self) -> int:
        async with self.session_factory() as session:
            setting = await HostProbeSettingsService(
                session,
                self.default_interval_minutes,
            ).get()
            return setting.interval_minutes

    async def probe_all(self) -> None:
        async with self.session_factory() as session:
            host_ids = list(await session.scalars(select(Host.id).order_by(Host.id)))

        semaphore = asyncio.Semaphore(self.concurrency)

        async def probe(host_id: str) -> None:
            async with semaphore:
                try:
                    async with self.session_factory() as session:
                        await HostService(
                            session,
                            self.cipher,
                            self.ssh_client,
                        ).test_connection(host_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Scheduled SSH probe failed for host %s", host_id)

        await asyncio.gather(*(probe(host_id) for host_id in host_ids))

    async def _run(self) -> None:
        while not self._stopping:
            self._wakeup.clear()
            try:
                await self.probe_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled host probe round failed")
            if self._stopping:
                break
            try:
                delay = (await self.interval_minutes()) * 60
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Could not load host probe interval; using configured default")
                delay = self.default_interval_minutes * 60
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=delay)
            except TimeoutError:
                pass
