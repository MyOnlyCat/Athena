import asyncio
import platform
import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select

from app.core.errors import AppError
from app.models.host import Host

InventoryStatus = Literal[
    "connecting",
    "online",
    "pending",
    "disabled",
    "rejected",
    "authentication_failed",
    "connection_failed",
    "error",
]

NORMAL_HEARTBEAT_SECONDS = 60
MANAGEMENT_PROBE_SECONDS = 300
CONNECTION_BACKOFF_BASE_SECONDS = 5
CONNECTION_BACKOFF_MAX_SECONDS = 300
AUTHENTICATION_ERROR_CODES = {
    "NODE_SIGNATURE_INVALID",
    "NODE_AUTH_INVALID",
    "REGISTRATION_TOKEN_INVALID",
}


def _read(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name)


def _utc_rfc3339(value: datetime) -> str:
    normalized = value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def _public_host(item: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    result = {field: _read(item, field) for field in fields}
    tested_at = result["last_tested_at"]
    if isinstance(tested_at, datetime):
        result["last_tested_at"] = _utc_rfc3339(tested_at)
    return result


def build_inventory(
    *,
    node_id: str,
    node_name: str,
    version: str,
    hosts: list[Any],
) -> dict[str, Any]:
    public_fields = (
        "id",
        "name",
        "address",
        "port",
        "username",
        "tags",
        "is_local",
        "last_test_status",
        "last_test_code",
        "last_tested_at",
    )
    return {
        "protocol_version": "v1",
        "node": {
            "id": node_id,
            "name": node_name,
            "version": version,
            "hostname": platform.node(),
            "reported_at": _utc_rfc3339(datetime.now(UTC)),
        },
        "hosts": [
            _public_host(host, public_fields)
            for host in hosts
        ],
    }


class InventorySynchronizer:
    def __init__(
        self,
        settings: Any,
        session_factory: Any,
        master_client: Any = None,
        *,
        jitter_source: Callable[[], float] = random.random,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.master_client = master_client
        self.jitter_source = jitter_source
        self.changed = asyncio.Event()
        self.last_success_at: datetime | None = None
        self.status: InventoryStatus = "connecting"
        self._connection_failures = 0

    def notify_change(self) -> None:
        self.changed.set()

    async def sync_now(self) -> None:
        if self.master_client is None or self.session_factory is None:
            return
        self.status = "connecting"
        try:
            async with self.session_factory() as session:
                hosts = list(
                    (await session.scalars(select(Host).order_by(Host.name))).all()
                )
            payload = build_inventory(
                node_id=self.settings.node_id,
                node_name=self.settings.node_name,
                version=self.settings.node_version,
                hosts=hosts,
            )
            await self.master_client.heartbeat(payload)
        except AppError as exc:
            if exc.code == "NODE_DISABLED":
                self.status = "disabled"
            elif exc.code in AUTHENTICATION_ERROR_CODES:
                self.status = "authentication_failed"
            elif exc.code in {"NODE_NOT_FOUND", "NODE_NOT_APPROVED"}:
                self.status = "pending"
            elif exc.code == "REGISTRATION_REJECTED":
                self.status = "rejected"
            else:
                self.status = "error"
            raise
        except Exception:
            self.status = "connection_failed"
            raise
        self.last_success_at = datetime.now(UTC)
        self.status = "online"

    def _retry_delay(self) -> float | None:
        if self.status in {"disabled", "authentication_failed"}:
            self._connection_failures = 0
            return MANAGEMENT_PROBE_SECONDS
        if self.status == "rejected":
            self._connection_failures = 0
            return None
        if self.status == "connection_failed":
            self._connection_failures += 1
            exponent = min(self._connection_failures - 1, 6)
            base_delay = min(
                CONNECTION_BACKOFF_MAX_SECONDS,
                CONNECTION_BACKOFF_BASE_SECONDS * 2**exponent,
            )
            jittered = base_delay * (0.5 + self.jitter_source())
            return float(min(CONNECTION_BACKOFF_MAX_SECONDS, jittered))
        self._connection_failures = 0
        return NORMAL_HEARTBEAT_SECONDS

    async def run(self, stop: asyncio.Event, claim_callback: Any = None) -> None:
        while not stop.is_set():
            self.changed.clear()
            try:
                await self.sync_now()
                if claim_callback is not None:
                    await claim_callback()
            except Exception:
                if self.status == "online":
                    self.status = "connection_failed"
            delay = self._retry_delay()
            if stop.is_set():
                break
            try:
                if delay is None:
                    await self.changed.wait()
                else:
                    await asyncio.wait_for(self.changed.wait(), timeout=delay)
            except TimeoutError:
                pass
