import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.core.time import as_utc
from app.models.registration import AccessNode, RegistrationApplication
from app.schemas.registration import (
    NONCE_PATTERN,
    SIGNATURE_PATTERN,
    RegistrationApplicationStatus,
    RegistrationPayload,
)
from app.services.audit import AuditedAction, commit_with_audit
from app.services.crypto import CredentialCipher, node_token_fingerprint
from app.services.signing import verify_request_signature

REGISTRATION_PATH = "/api/node/v1/registration-applications"
REGISTRATION_STATUS_PATH = "/api/node/v1/registration-applications/status"
TIMESTAMP_WINDOW_SECONDS = 300
APPLICATION_EXPIRY_DAYS = 7
TERMINAL_RETENTION_DAYS = 30
NODE_RATE_WINDOW_SECONDS = 60
IP_RATE_LIMIT = 10
PENDING_APPLICATION_LIMIT = 1_000


class RegistrationThrottle:
    def __init__(self) -> None:
        self._node_attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._ip_attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._last_cleanup: datetime | None = None

    @staticmethod
    def _prune(attempts: deque[datetime], cutoff: datetime) -> None:
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

    def _cleanup(self, cutoff: datetime, now: datetime) -> None:
        if (
            self._last_cleanup is not None
            and now - self._last_cleanup < timedelta(seconds=NODE_RATE_WINDOW_SECONDS)
        ):
            return
        for buckets in (self._node_attempts, self._ip_attempts):
            for key, attempts in list(buckets.items()):
                self._prune(attempts, cutoff)
                if not attempts:
                    del buckets[key]
        self._last_cleanup = now

    def _record_attempt_and_report_limit(
        self,
        buckets: dict[str, deque[datetime]],
        key: str,
        *,
        limit: int,
        cutoff: datetime,
        now: datetime,
    ) -> bool:
        attempts = buckets[key]
        self._prune(attempts, cutoff)
        limited = len(attempts) >= limit
        attempts.append(now)
        while len(attempts) > limit:
            attempts.popleft()
        return limited

    def check_and_record(
        self,
        *,
        node_id: str,
        source_ip: str | None,
        now: datetime,
    ) -> None:
        cutoff = now - timedelta(seconds=NODE_RATE_WINDOW_SECONDS)
        self._cleanup(cutoff, now)
        node_limited = self._record_attempt_and_report_limit(
            self._node_attempts,
            node_id,
            limit=1,
            cutoff=cutoff,
            now=now,
        )
        ip_limited = self._record_attempt_and_report_limit(
            self._ip_attempts,
            source_ip or "<unknown>",
            limit=IP_RATE_LIMIT,
            cutoff=cutoff,
            now=now,
        )
        if node_limited or ip_limited:
            raise AppError(
                "REGISTRATION_RATE_LIMITED",
                "注册申请过于频繁，请稍后重试",
                status_code=429,
            )


class RegistrationService:
    def __init__(
        self,
        session: AsyncSession,
        credential_key: str,
        throttle: RegistrationThrottle | None = None,
    ) -> None:
        self.session = session
        self.cipher = CredentialCipher(credential_key)
        self.credential_key = credential_key
        self.throttle = throttle

    def _token_fingerprint(self, token: str) -> str:
        return node_token_fingerprint(self.credential_key, token)

    async def maintain(self, now: datetime) -> None:
        expiry_cutoff = now - timedelta(days=APPLICATION_EXPIRY_DAYS)
        await self.session.execute(
            update(RegistrationApplication)
            .where(
                RegistrationApplication.status == "pending",
                RegistrationApplication.received_at <= expiry_cutoff,
            )
            .values(status="expired", status_changed_at=now)
        )
        retention_cutoff = now - timedelta(days=TERMINAL_RETENTION_DAYS)
        await self.session.execute(
            delete(RegistrationApplication).where(
                RegistrationApplication.status.in_(("rejected", "expired")),
                RegistrationApplication.status_changed_at <= retention_cutoff,
            )
        )
        await self.session.commit()

    async def backfill_token_fingerprints(self) -> None:
        nodes = list(
            (
                await self.session.scalars(
                    select(AccessNode).where(AccessNode.token_fingerprint.is_(None))
                )
            ).all()
        )
        fingerprints = {
            fingerprint
            for fingerprint in (
                await self.session.scalars(
                    select(AccessNode.token_fingerprint).where(
                        AccessNode.token_fingerprint.is_not(None)
                    )
                )
            ).all()
            if fingerprint is not None
        }
        for node in nodes:
            fingerprint = self._token_fingerprint(
                self.cipher.decrypt(node.encrypted_token)
            )
            if fingerprint in fingerprints:
                raise RuntimeError(
                    "数据库中存在重复的 Node Token，必须先为受影响节点配置不同 Token"
                )
            fingerprints.add(fingerprint)
            node.token_fingerprint = fingerprint
        await self.session.commit()

    async def _latest_application(self, node_id: str) -> RegistrationApplication | None:
        return cast(
            RegistrationApplication | None,
            await self.session.scalar(
                select(RegistrationApplication)
                .where(RegistrationApplication.node_id == node_id)
                .order_by(
                    RegistrationApplication.received_at.desc(),
                    RegistrationApplication.id.desc(),
                )
                .limit(1)
            )
        )

    async def submit(
        self,
        *,
        body: bytes,
        node_id: str,
        timestamp: str,
        nonce: str,
        signature: str,
        source_ip: str | None,
        received_at: datetime,
    ) -> RegistrationApplication:
        try:
            payload = RegistrationPayload.model_validate_json(body)
            timestamp_seconds = int(timestamp)
        except (ValueError, TypeError):
            raise AppError(
                "REGISTRATION_PAYLOAD_INVALID",
                "注册申请参数无效",
                status_code=422,
            ) from None
        if payload.node_id != node_id:
            raise AppError(
                "REGISTRATION_IDENTITY_MISMATCH",
                "请求身份与注册正文不一致",
                status_code=422,
            )
        if not NONCE_PATTERN.fullmatch(nonce) or not SIGNATURE_PATTERN.fullmatch(signature):
            raise AppError(
                "REGISTRATION_AUTH_INVALID",
                "注册申请认证头无效",
                status_code=422,
            )
        if abs(received_at.timestamp() - timestamp_seconds) > TIMESTAMP_WINDOW_SECONDS:
            raise AppError(
                "NODE_TIMESTAMP_INVALID",
                "节点时间戳无效",
                status_code=401,
            )
        await self.maintain(received_at)
        if self.throttle is None:
            raise RuntimeError("registration throttle is not configured")
        self.throttle.check_and_record(
            node_id=payload.node_id,
            source_ip=source_ip,
            now=received_at,
        )
        latest = await self._latest_application(payload.node_id)
        if latest is not None and latest.status == "rejected":
            raise AppError(
                "REGISTRATION_REJECTED",
                "接入申请已被拒绝，请联系管理员恢复后手动重试",
                status_code=409,
            )
        pending_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(RegistrationApplication)
                .where(RegistrationApplication.status == "pending")
            )
            or 0
        )
        if pending_count >= PENDING_APPLICATION_LIMIT:
            raise AppError(
                "REGISTRATION_CAPACITY_REACHED",
                "待审批注册申请已达容量上限",
                status_code=429,
            )
        application = RegistrationApplication(
            node_id=payload.node_id,
            reported_name=payload.reported_name,
            hostname=payload.hostname,
            software_version=payload.software_version,
            raw_body=body,
            request_path=REGISTRATION_PATH,
            auth_timestamp=timestamp,
            auth_nonce=nonce,
            auth_signature=signature,
            source_ip=source_ip,
            received_at=received_at,
        )
        self.session.add(application)
        await self.session.commit()
        await self.session.refresh(application)
        return application

    async def list_page(
        self,
        page: int,
        page_size: int,
    ) -> tuple[list[RegistrationApplication], int]:
        await self.maintain(datetime.now(UTC))
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(RegistrationApplication)
            )
            or 0
        )
        applications = list(
            (
                await self.session.scalars(
                    select(RegistrationApplication)
                    .order_by(
                        RegistrationApplication.received_at.desc(),
                        RegistrationApplication.id,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return applications, total

    async def status(
        self,
        *,
        body: bytes,
        node_id: str,
        timestamp: str,
        nonce: str,
        signature: str,
        received_at: datetime,
    ) -> RegistrationApplicationStatus:
        try:
            timestamp_seconds = int(timestamp)
        except (ValueError, TypeError):
            raise AppError(
                "REGISTRATION_AUTH_INVALID",
                "注册状态查询认证头无效",
                status_code=422,
            ) from None
        if (
            not NONCE_PATTERN.fullmatch(nonce)
            or not SIGNATURE_PATTERN.fullmatch(signature)
            or abs(received_at.timestamp() - timestamp_seconds)
            > TIMESTAMP_WINDOW_SECONDS
        ):
            raise AppError(
                "REGISTRATION_AUTH_INVALID",
                "注册状态查询认证头无效",
                status_code=401,
            )
        await self.maintain(received_at)
        node = await self.session.get(AccessNode, node_id)
        if node is None:
            latest = await self._latest_application(node_id)
            if latest is not None:
                return cast(RegistrationApplicationStatus, latest.status)
            raise AppError(
                "NODE_NOT_APPROVED",
                "节点尚未批准",
                status_code=404,
            )
        token = self.cipher.decrypt(node.encrypted_token)
        if not verify_request_signature(
            secret=token,
            method="POST",
            path_with_query=REGISTRATION_STATUS_PATH,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
            signature=signature,
        ):
            raise AppError(
                "REGISTRATION_TOKEN_INVALID",
                "Token 与已批准节点不匹配",
                status_code=401,
            )
        return "approved"

    async def approve(
        self,
        application_id: str,
        token: str,
        audit: AuditedAction | None = None,
    ) -> AccessNode:
        await self.maintain(datetime.now(UTC))
        application = await self.session.get(RegistrationApplication, application_id)
        if application is None:
            raise AppError("REGISTRATION_NOT_FOUND", "注册申请不存在", status_code=404)
        if audit is not None:
            audit.set_target(application.id, application.reported_name)
        if application.status == "expired":
            raise AppError(
                "REGISTRATION_EXPIRED",
                "注册申请已过期",
                status_code=409,
            )
        if application.status != "pending":
            raise AppError(
                "REGISTRATION_NOT_PENDING",
                "注册申请已处理",
                status_code=409,
            )
        received_at = as_utc(application.received_at)
        if (
            abs(received_at.timestamp() - int(application.auth_timestamp))
            > TIMESTAMP_WINDOW_SECONDS
        ):
            raise AppError(
                "NODE_TIMESTAMP_INVALID",
                "节点时间戳无效",
                status_code=401,
            )
        signature_valid = verify_request_signature(
            secret=token,
            method="POST",
            path_with_query=application.request_path,
            timestamp=application.auth_timestamp,
            nonce=application.auth_nonce,
            body=application.raw_body,
            signature=application.auth_signature,
        )
        if not signature_valid:
            raise AppError(
                "REGISTRATION_TOKEN_INVALID",
                "Token 与注册申请不匹配",
                status_code=401,
            )
        existing = await self.session.get(AccessNode, application.node_id)
        if existing is not None:
            raise AppError("NODE_ALREADY_EXISTS", "接入节点已存在", status_code=409)
        token_fingerprint = self._token_fingerprint(token)
        token_owner = await self.session.scalar(
            select(AccessNode.node_id).where(
                AccessNode.token_fingerprint == token_fingerprint
            )
        )
        if token_owner is not None:
            raise AppError(
                "REGISTRATION_TOKEN_DUPLICATE",
                "Token 已被其他接入节点使用",
                status_code=409,
            )
        node = AccessNode(
            node_id=application.node_id,
            reported_name=application.reported_name,
            hostname=application.hostname,
            software_version=application.software_version,
            encrypted_token=self.cipher.encrypt(token),
            token_fingerprint=token_fingerprint,
        )
        application.status = "approved"
        application.status_changed_at = datetime.now(UTC)
        self.session.add(node)
        try:
            await commit_with_audit(self.session, audit)
        except IntegrityError:
            await self.session.rollback()
            token_owner = await self.session.scalar(
                select(AccessNode.node_id).where(
                    AccessNode.token_fingerprint == token_fingerprint
                )
            )
            if token_owner is not None:
                raise AppError(
                    "REGISTRATION_TOKEN_DUPLICATE",
                    "Token 已被其他接入节点使用",
                    status_code=409,
                ) from None
            raise
        await self.session.refresh(node)
        return node

    async def reject(
        self,
        application_id: str,
        reason: str | None,
        audit: AuditedAction | None = None,
    ) -> RegistrationApplication:
        await self.maintain(datetime.now(UTC))
        application = await self.session.get(RegistrationApplication, application_id)
        if application is None:
            raise AppError("REGISTRATION_NOT_FOUND", "注册申请不存在", status_code=404)
        if audit is not None:
            audit.set_target(application.id, application.reported_name)
        if application.status != "pending":
            raise AppError(
                "REGISTRATION_NOT_PENDING",
                "注册申请已处理",
                status_code=409,
            )
        application.status = "rejected"
        application.rejection_reason = reason.strip() if reason and reason.strip() else None
        application.status_changed_at = datetime.now(UTC)
        await commit_with_audit(self.session, audit)
        await self.session.refresh(application)
        return application

    async def restore(
        self,
        application_id: str,
        audit: AuditedAction | None = None,
    ) -> RegistrationApplication:
        await self.maintain(datetime.now(UTC))
        application = await self.session.get(RegistrationApplication, application_id)
        if application is None:
            raise AppError("REGISTRATION_NOT_FOUND", "注册申请不存在", status_code=404)
        if audit is not None:
            audit.set_target(application.id, application.reported_name)
        if application.status != "rejected":
            raise AppError(
                "REGISTRATION_NOT_REJECTED",
                "仅已拒绝的注册申请可以恢复",
                status_code=409,
            )
        application.status = "restored"
        application.rejection_reason = None
        application.status_changed_at = datetime.now(UTC)
        await commit_with_audit(self.session, audit)
        await self.session.refresh(application)
        return application


async def registration_maintenance_loop(
    session_factory: async_sessionmaker[AsyncSession],
    credential_key: str,
    write_lock: asyncio.Lock,
) -> None:
    while True:
        await asyncio.sleep(3_600)
        async with write_lock:
            async with session_factory() as session:
                service = RegistrationService(session, credential_key)
                await service.backfill_token_fingerprints()
                await service.maintain(datetime.now(UTC))
