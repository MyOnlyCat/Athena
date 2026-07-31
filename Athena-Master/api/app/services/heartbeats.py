from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.registration import AccessNode, NodeNonce
from app.schemas.heartbeat import ConnectivityStatus, HeartbeatPayload
from app.schemas.registration import NONCE_PATTERN, SIGNATURE_PATTERN
from app.services.crypto import CredentialCipher
from app.services.signing import verify_request_signature

TIMESTAMP_WINDOW_SECONDS = 300
NONCE_RETENTION_MINUTES = 10
MIN_HEARTBEAT_INTERVAL_SECONDS = 10
NODE_REQUEST_LIMIT_PER_MINUTE = 20
SUPPORTED_PROTOCOL_VERSION = "v1"


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def connectivity_status(
    last_heartbeat_at: datetime | None,
    now: datetime,
) -> ConnectivityStatus:
    if last_heartbeat_at is None:
        return "offline"
    age = utc(now) - utc(last_heartbeat_at)
    if age < timedelta(seconds=120):
        return "online"
    if age <= timedelta(seconds=300):
        return "stale"
    return "offline"


class NodeRequestThrottle:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[datetime]] = defaultdict(deque)

    def check_and_record(self, node_id: str, now: datetime) -> None:
        attempts = self._attempts[node_id]
        cutoff = now - timedelta(minutes=1)
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= NODE_REQUEST_LIMIT_PER_MINUTE:
            raise AppError(
                "NODE_RATE_LIMITED",
                "节点请求过于频繁，请稍后重试",
                status_code=429,
            )
        attempts.append(now)


class HeartbeatService:
    def __init__(
        self,
        session: AsyncSession,
        credential_key: str,
        throttle: NodeRequestThrottle,
    ) -> None:
        self.session = session
        self.cipher = CredentialCipher(credential_key)
        self.throttle = throttle

    async def accept(
        self,
        *,
        body: bytes,
        path_with_query: str,
        node_id: str,
        timestamp: str,
        nonce: str,
        signature: str,
        received_at: datetime,
    ) -> datetime:
        timestamp_seconds = self._validate_auth_headers(
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        )
        if abs(received_at.timestamp() - timestamp_seconds) > TIMESTAMP_WINDOW_SECONDS:
            raise AppError(
                "NODE_TIMESTAMP_INVALID",
                "节点时间戳无效",
                status_code=401,
            )

        node = await self.session.get(AccessNode, node_id)
        if node is None:
            raise AppError("NODE_NOT_FOUND", "接入节点不存在", status_code=404)
        token = self.cipher.decrypt(node.encrypted_token)
        if not verify_request_signature(
            secret=token,
            method="POST",
            path_with_query=path_with_query,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
            signature=signature,
        ):
            raise AppError(
                "NODE_SIGNATURE_INVALID",
                "节点签名无效",
                status_code=401,
            )

        cutoff = received_at - timedelta(minutes=NONCE_RETENTION_MINUTES)
        await self.session.execute(delete(NodeNonce).where(NodeNonce.received_at <= cutoff))
        if await self.session.get(NodeNonce, (node_id, nonce)) is not None:
            raise AppError(
                "NODE_NONCE_REPLAYED",
                "节点 nonce 已被使用",
                status_code=409,
            )

        self.throttle.check_and_record(node_id, received_at)
        if (
            node.last_heartbeat_at is not None
            and received_at - utc(node.last_heartbeat_at)
            < timedelta(seconds=MIN_HEARTBEAT_INTERVAL_SECONDS)
        ):
            raise AppError(
                "NODE_RATE_LIMITED",
                "心跳请求过于频繁，请稍后重试",
                status_code=429,
            )

        payload = self._parse_payload(body)
        if payload.node.id != node_id:
            raise AppError(
                "NODE_PAYLOAD_INVALID",
                "心跳负载中的节点身份不匹配",
                status_code=422,
            )
        if payload.protocol_version != SUPPORTED_PROTOCOL_VERSION:
            raise AppError(
                "NODE_PROTOCOL_UNSUPPORTED",
                "节点协议版本不受支持",
                status_code=426,
            )

        node.reported_name = payload.node.name
        node.hostname = payload.node.hostname
        node.software_version = payload.node.version
        node.last_heartbeat_at = received_at
        self.session.add(NodeNonce(node_id=node_id, nonce=nonce, received_at=received_at))
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise AppError(
                "NODE_NONCE_REPLAYED",
                "节点 nonce 已被使用",
                status_code=409,
            ) from None
        return received_at

    @staticmethod
    def _validate_auth_headers(
        *,
        timestamp: str,
        nonce: str,
        signature: str,
    ) -> int:
        try:
            timestamp_seconds = int(timestamp)
        except (TypeError, ValueError):
            raise AppError(
                "NODE_AUTH_INVALID",
                "节点认证头无效",
                status_code=422,
            ) from None
        if not NONCE_PATTERN.fullmatch(nonce) or not SIGNATURE_PATTERN.fullmatch(signature):
            raise AppError(
                "NODE_AUTH_INVALID",
                "节点认证头无效",
                status_code=422,
            )
        return timestamp_seconds

    @staticmethod
    def _parse_payload(body: bytes) -> HeartbeatPayload:
        try:
            return HeartbeatPayload.model_validate_json(body)
        except ValidationError:
            raise AppError(
                "NODE_PAYLOAD_INVALID",
                "心跳负载无效",
                status_code=422,
            ) from None


class AccessNodeQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        management_status: str | None,
        requested_connectivity: ConnectivityStatus | None,
        sort_by: str,
        sort_order: str,
        now: datetime,
    ) -> tuple[list[AccessNode], int]:
        query = select(AccessNode)
        count_query = select(func.count()).select_from(AccessNode)
        conditions = []
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            conditions.append(
                or_(
                    AccessNode.node_id.ilike(pattern),
                    AccessNode.reported_name.ilike(pattern),
                    AccessNode.hostname.ilike(pattern),
                    AccessNode.software_version.ilike(pattern),
                )
            )
        if management_status is not None:
            conditions.append(AccessNode.management_status == management_status)
        if requested_connectivity is not None:
            online_cutoff = now - timedelta(seconds=120)
            offline_cutoff = now - timedelta(seconds=300)
            if requested_connectivity == "online":
                conditions.append(AccessNode.last_heartbeat_at > online_cutoff)
            elif requested_connectivity == "stale":
                conditions.extend(
                    (
                        AccessNode.last_heartbeat_at <= online_cutoff,
                        AccessNode.last_heartbeat_at >= offline_cutoff,
                    )
                )
            else:
                conditions.append(
                    or_(
                        AccessNode.last_heartbeat_at.is_(None),
                        AccessNode.last_heartbeat_at < offline_cutoff,
                    )
                )
        if conditions:
            query = query.where(*conditions)
            count_query = count_query.where(*conditions)

        sort_columns = {
            "reported_name": AccessNode.reported_name,
            "hostname": AccessNode.hostname,
            "software_version": AccessNode.software_version,
            "approved_at": AccessNode.approved_at,
            "last_heartbeat_at": AccessNode.last_heartbeat_at,
        }
        sort_column = sort_columns[sort_by]
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        query = query.order_by(ordering, AccessNode.node_id.asc())
        total = int(await self.session.scalar(count_query) or 0)
        nodes = list(
            (
                await self.session.scalars(
                    query.offset((page - 1) * page_size).limit(page_size)
                )
            ).all()
        )
        return nodes, total
