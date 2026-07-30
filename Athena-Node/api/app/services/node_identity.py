import secrets
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.node_identity import NodeIdentity


def generate_uuid7() -> str:
    value = bytearray(
        (time.time_ns() // 1_000_000).to_bytes(6, "big") + secrets.token_bytes(10)
    )
    value[6] = (value[6] & 0x0F) | 0x70
    value[8] = (value[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(value)))


def validate_uuid7(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("测试节点身份必须是 UUIDv7") from exc
    if parsed.version != 7:
        raise ValueError("测试节点身份必须是 UUIDv7")
    return str(parsed)


@dataclass(frozen=True)
class PersistedNodeIdentity:
    node_id: str
    reported_name: str


class NodeIdentityService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def get_or_create(self) -> PersistedNodeIdentity:
        row = await self.session.get(NodeIdentity, 1)
        if row is None:
            injected_id = (
                validate_uuid7(self.settings.node_id.strip())
                if self.settings.environment == "test"
                and self.settings.node_id.strip()
                else ""
            )
            row = NodeIdentity(
                id=1,
                node_id=injected_id or generate_uuid7(),
                reported_name=self.settings.node_name,
            )
            self.session.add(row)
            await self.session.commit()
        return PersistedNodeIdentity(row.node_id, row.reported_name)
