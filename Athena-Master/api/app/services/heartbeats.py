from collections import defaultdict, deque
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import as_utc
from app.models.registration import AccessNode, NodeNonce
from app.schemas.heartbeat import HeartbeatPayload
from app.schemas.registration import NONCE_PATTERN, SIGNATURE_PATTERN
from app.services.assets import AssetSnapshotService
from app.services.crypto import CredentialCipher
from app.services.signing import verify_request_signature

TIMESTAMP_WINDOW_SECONDS = 300
NONCE_RETENTION_MINUTES = 10
MIN_HEARTBEAT_INTERVAL_SECONDS = 10
NODE_REQUEST_LIMIT_PER_MINUTE = 20
SUPPORTED_PROTOCOL_VERSION = "v1"
MAX_HEARTBEAT_BODY_BYTES = 5 * 1024 * 1024


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

        if node.management_status == "disabled":
            raise AppError(
                "NODE_DISABLED",
                "接入节点已被禁用",
                status_code=403,
            )
        if node.management_status != "active":
            raise AppError(
                "NODE_NOT_ACTIVE",
                "接入节点当前不可用",
                status_code=403,
            )

        cutoff = received_at - timedelta(minutes=NONCE_RETENTION_MINUTES)
        await self.session.execute(delete(NodeNonce).where(NodeNonce.received_at <= cutoff))
        if await self.session.get(NodeNonce, (node_id, nonce)) is not None:
            raise AppError(
                "NODE_NONCE_REPLAYED",
                "节点 nonce 已被使用",
                status_code=409,
            )

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

        self.throttle.check_and_record(node_id, received_at)
        if (
            node.last_heartbeat_at is not None
            and received_at - as_utc(node.last_heartbeat_at)
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

        await AssetSnapshotService(self.session).replace(
            node_id=node_id,
            hosts=payload.hosts,
            received_at=received_at,
        )
        node.reported_name = payload.node.name
        node.hostname = payload.node.hostname
        node.software_version = payload.node.version
        node.last_heartbeat_at = received_at
        await self.session.commit()
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
