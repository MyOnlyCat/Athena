import asyncio
from collections.abc import Callable
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError
from app.services.crypto import CredentialCipher
from app.services.executor import DeploymentExecutor
from app.services.inventory_sync import InventorySynchronizer, build_inventory
from app.services.master_client import MasterClient
from app.services.master_settings import MasterConfig

RuntimeCallback = Callable[[Any | None, Any | None], None]


class MasterRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: Any,
        artifact_service: Any,
        gateway: Any,
        cipher: CredentialCipher,
        client_factory: Callable[..., Any] = MasterClient,
        inventory_factory: Callable[..., Any] = InventorySynchronizer,
        executor_factory: Callable[..., Any] = DeploymentExecutor,
        start_worker: bool = True,
        on_change: RuntimeCallback | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.artifact_service = artifact_service
        self.gateway = gateway
        self.cipher = cipher
        self.client_factory = client_factory
        self.inventory_factory = inventory_factory
        self.executor_factory = executor_factory
        self.start_worker = start_worker
        self.on_change = on_change
        self._lock = asyncio.Lock()
        self._client: Any | None = None
        self._inventory: Any | None = None
        self._executor: Any | None = None
        self._stop_event: asyncio.Event | None = None
        self._worker: asyncio.Task[None] | None = None

    @property
    def status(self) -> str:
        if self._worker is not None and not self._worker.done():
            return "running"
        if self._client is not None:
            return "configured"
        return "stopped"

    async def test(self, config: MasterConfig) -> None:
        client = self.client_factory(
            config.base_url,
            self.settings.node_id,
            config.token,
        )
        try:
            payload = build_inventory(
                node_id=self.settings.node_id,
                node_name=self.settings.node_name,
                version=self.settings.node_version,
                hosts=[],
            )
            await client.test_connection(payload)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "MASTER_CONNECTION_FAILED",
                "Unable to connect to the master node",
            ) from exc
        finally:
            await client.close()

    async def apply(self, config: MasterConfig) -> None:
        async with self._lock:
            await self._stop_locked()
            if not config.host or not config.token:
                return

            client = self.client_factory(
                config.base_url,
                self.settings.node_id,
                config.token,
            )
            try:
                inventory = self.inventory_factory(
                    self.settings,
                    self.session_factory,
                    client,
                )
                executor = self.executor_factory(
                    session_factory=self.session_factory,
                    master_client=client,
                    artifact_service=self.artifact_service,
                    gateway=self.gateway,
                    cipher=self.cipher,
                    concurrency=self.settings.deploy_concurrency,
                )
                self._client = client
                self._inventory = inventory
                self._executor = executor
                self._publish()
                if self.start_worker:
                    await executor.recover()
                    self._stop_event = asyncio.Event()
                    self._worker = asyncio.create_task(
                        inventory.run(self._stop_event, executor.poll),
                        name="master-runtime",
                    )
            except Exception:
                if self._client is client:
                    await self._stop_locked()
                else:
                    await client.close()
                raise

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        stop_event = self._stop_event
        worker = self._worker
        inventory = self._inventory
        executor = self._executor
        client = self._client
        self._stop_event = None
        self._worker = None
        self._inventory = None
        self._executor = None
        self._client = None

        if stop_event is not None:
            stop_event.set()
        if inventory is not None:
            inventory.notify_change()
        if worker is not None:
            await worker
        if executor is not None:
            await executor.close()
        if client is not None:
            await client.close()
        self._publish()

    def _publish(self) -> None:
        if self.on_change is not None:
            self.on_change(self._inventory, self._executor)
