import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from app.core.config import Settings
from app.core.errors import AppError
from app.services.crypto import CredentialCipher
from app.services.executor import DeploymentExecutor
from app.services.inventory_sync import InventorySynchronizer, build_inventory
from app.services.master_client import MasterClient
from app.services.master_settings import MasterConfig

RuntimeCallback = Callable[[Any | None, Any | None], None]
WorkerCoroutine = Coroutine[Any, Any, None]
TaskFactory = Callable[..., asyncio.Task[None]]
ShieldedResult = TypeVar("ShieldedResult")


@dataclass
class RuntimeSlot:
    config: MasterConfig
    client: Any | None = None
    inventory: Any | None = None
    executor: Any | None = None
    stop_event: asyncio.Event | None = None
    activation_event: asyncio.Event | None = None
    worker: asyncio.Task[None] | None = None

    @property
    def has_resources(self) -> bool:
        return self.worker is not None or self.executor is not None or self.client is not None


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
        task_factory: TaskFactory = asyncio.create_task,
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
        self.task_factory = task_factory
        self.start_worker = start_worker
        self.on_change = on_change
        self._lock = asyncio.Lock()
        self._active: RuntimeSlot | None = None
        self._retired: list[RuntimeSlot] = []

    @property
    def status(self) -> str:
        slot = self._active
        if slot is None:
            return "stopped"
        if slot.worker is not None and not slot.worker.done():
            return "running"
        if slot.client is not None:
            return "configured"
        return "stopped"

    @asynccontextmanager
    async def reconfigure(self) -> AsyncIterator[None]:
        async with self._lock:
            yield

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

    async def prepare(self, config: MasterConfig) -> RuntimeSlot:
        candidate = RuntimeSlot(config=config)
        if not config.host or not config.token:
            return candidate

        try:
            candidate.client = self.client_factory(
                config.base_url,
                self.settings.node_id,
                config.token,
            )
            candidate.inventory = self.inventory_factory(
                self.settings,
                self.session_factory,
                candidate.client,
            )
            candidate.executor = self.executor_factory(
                session_factory=self.session_factory,
                master_client=candidate.client,
                artifact_service=self.artifact_service,
                gateway=self.gateway,
                cipher=self.cipher,
                concurrency=self.settings.deploy_concurrency,
            )
            if self.start_worker:
                candidate.stop_event = asyncio.Event()
                candidate.activation_event = asyncio.Event()
                ready = asyncio.Event()
                worker_coroutine = self._run_candidate(candidate, ready)
                try:
                    candidate.worker = self.task_factory(
                        worker_coroutine,
                        name="master-runtime",
                    )
                except BaseException:
                    worker_coroutine.close()
                    raise
                await ready.wait()
                if candidate.worker.done():
                    await candidate.worker
        except BaseException as exc:
            cleanup_errors = await self._shielded(
                self._cleanup_slot(candidate),
                name="master-runtime-prepare-cleanup",
            )
            if candidate.has_resources:
                self._retired.append(candidate)
            for error in cleanup_errors:
                exc.add_note(f"candidate cleanup failed: {error!r}")
            raise
        return candidate

    async def activate(self, candidate: RuntimeSlot) -> None:
        await self._shielded(
            self._activate_owned(candidate),
            name="master-runtime-activation",
        )

    async def _activate_owned(self, candidate: RuntimeSlot) -> None:
        previous = self._active
        self._active = None
        if previous is not None:
            cleanup_errors = await self._drain_worker(previous)
            cleanup_errors.extend(await self._close_resources(previous))
            self._retain_retired(previous, cleanup_errors)

        if not candidate.has_resources:
            self._publish(None, None)
            return

        self._active = candidate
        self._publish(candidate.inventory, candidate.executor)
        if candidate.activation_event is not None:
            candidate.activation_event.set()

    async def discard(self, candidate: RuntimeSlot) -> None:
        if candidate is self._active:
            return
        await self._shielded(
            self._retire(candidate),
            name="master-runtime-discard",
        )

    async def apply(self, config: MasterConfig, *, recover: bool = False) -> None:
        async with self.reconfigure():
            candidate = await self.prepare(config)
            try:
                if recover and candidate.executor is not None:
                    await candidate.executor.recover()
            except BaseException:
                await self.discard(candidate)
                raise
            await self.activate(candidate)

    async def stop(self) -> None:
        async with self.reconfigure():
            await self._shielded(
                self._stop_owned(),
                name="master-runtime-stop",
            )

    async def _stop_owned(self) -> None:
        cleanup_errors: list[Exception] = []
        pending_retired = self._retired
        self._retired = []
        retained: list[RuntimeSlot] = []
        active = self._active
        self._active = None
        if active is not None:
            cleanup_errors.extend(await self._cleanup_slot(active))
            if active.has_resources:
                retained.append(active)

        for slot in pending_retired:
            cleanup_errors.extend(await self._cleanup_slot(slot))
            if slot.has_resources:
                retained.append(slot)
        self._retired = retained
        cleanup_errors.extend(self._publish(None, None))

        if cleanup_errors:
            raise ExceptionGroup("master runtime cleanup failed", cleanup_errors)

    async def _run_candidate(
        self,
        candidate: RuntimeSlot,
        ready: asyncio.Event,
    ) -> None:
        ready.set()
        activation_event = candidate.activation_event
        stop_event = candidate.stop_event
        if activation_event is None or stop_event is None:
            return
        await activation_event.wait()
        if stop_event.is_set():
            return
        inventory = candidate.inventory
        executor = candidate.executor
        if inventory is None or executor is None:
            return
        await inventory.run(stop_event, executor.poll)

    async def _retire(self, slot: RuntimeSlot) -> None:
        cleanup_errors = await self._cleanup_slot(slot)
        self._retain_retired(slot, cleanup_errors)

    async def _cleanup_slot(self, slot: RuntimeSlot) -> list[Exception]:
        errors = await self._drain_worker(slot)
        errors.extend(await self._close_resources(slot))
        return errors

    async def _drain_worker(self, slot: RuntimeSlot) -> list[Exception]:
        errors: list[Exception] = []
        if slot.stop_event is not None:
            slot.stop_event.set()
        if slot.activation_event is not None:
            slot.activation_event.set()

        if slot.inventory is not None:
            try:
                slot.inventory.notify_change()
            except BaseException as exc:
                errors.append(self._cleanup_error("inventory wakeup", exc))
            slot.inventory = None

        if slot.worker is not None:
            results = await asyncio.gather(slot.worker, return_exceptions=True)
            result = results[0]
            if isinstance(result, BaseException):
                errors.append(self._cleanup_error("worker stop", result))
            slot.worker = None
            slot.stop_event = None
            slot.activation_event = None

        return errors

    async def _close_resources(self, slot: RuntimeSlot) -> list[Exception]:
        errors: list[Exception] = []
        if slot.executor is not None:
            try:
                await slot.executor.close()
            except BaseException as exc:
                errors.append(self._cleanup_error("executor close", exc))
            else:
                slot.executor = None

        if slot.client is not None:
            try:
                await slot.client.close()
            except BaseException as exc:
                errors.append(self._cleanup_error("client close", exc))
            else:
                slot.client = None

        return errors

    def _retain_retired(
        self,
        slot: RuntimeSlot,
        cleanup_errors: list[Exception],
    ) -> None:
        if slot.has_resources and slot not in self._retired:
            self._retired.append(slot)
        for error in cleanup_errors:
            error.add_note("retired runtime cleanup will be retried during stop")

    async def _shielded(
        self,
        operation: Coroutine[Any, Any, ShieldedResult],
        *,
        name: str,
    ) -> ShieldedResult:
        task = asyncio.create_task(operation, name=name)
        cancellation: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                cancellation = exc

        try:
            result = task.result()
        except BaseException as operation_error:
            if cancellation is not None:
                cancellation.add_note(
                    f"{name} also failed: {operation_error!r}"
                )
                raise cancellation from operation_error
            raise
        if cancellation is not None:
            raise cancellation
        return result

    @staticmethod
    def _cleanup_error(stage: str, error: BaseException) -> Exception:
        if isinstance(error, Exception):
            return error
        wrapped = RuntimeError(f"{stage} was cancelled")
        wrapped.__cause__ = error
        return wrapped

    def _publish(
        self,
        inventory: Any | None,
        executor: Any | None,
    ) -> list[Exception]:
        if self.on_change is None:
            return []
        try:
            self.on_change(inventory, executor)
        except Exception as exc:
            return [exc]
        return []
