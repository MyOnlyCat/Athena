import asyncio
import platform
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select

from app.models.host import Host

InventoryStatus = Literal["connecting", "online", "error"]


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
    def __init__(self, settings: Any, session_factory: Any, master_client: Any = None) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.master_client = master_client
        self.changed = asyncio.Event()
        self.last_success_at: datetime | None = None
        self.status: InventoryStatus = "connecting"

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
        except Exception:
            self.status = "error"
            raise
        self.last_success_at = datetime.now(UTC)
        self.status = "online"

    async def run(self, stop: asyncio.Event, claim_callback: Any = None) -> None:
        while not stop.is_set():
            self.changed.clear()
            try:
                await self.sync_now()
                if claim_callback is not None:
                    await claim_callback()
            except Exception:
                self.status = "error"
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=60)
            except TimeoutError:
                pass
