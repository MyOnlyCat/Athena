import hashlib
import hmac
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.registration import AccessNode, RegistrationApplication
from app.schemas.registration import (
    NONCE_PATTERN,
    SIGNATURE_PATTERN,
    RegistrationPayload,
)
from app.services.crypto import CredentialCipher

REGISTRATION_PATH = "/api/node/v1/registration-applications"
TIMESTAMP_WINDOW_SECONDS = 300


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _signature(
    token: str,
    *,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    canonical = "\n".join(
        (
            "POST",
            path,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        )
    )
    return hmac.new(token.encode(), canonical.encode(), hashlib.sha256).hexdigest()


class RegistrationService:
    def __init__(self, session: AsyncSession, credential_key: str) -> None:
        self.session = session
        self.cipher = CredentialCipher(credential_key)

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

    async def approve(self, application_id: str, token: str) -> AccessNode:
        application = await self.session.get(RegistrationApplication, application_id)
        if application is None:
            raise AppError("REGISTRATION_NOT_FOUND", "注册申请不存在", status_code=404)
        if application.status != "pending":
            raise AppError(
                "REGISTRATION_NOT_PENDING",
                "注册申请已处理",
                status_code=409,
            )
        received_at = _utc(application.received_at)
        if (
            abs(received_at.timestamp() - int(application.auth_timestamp))
            > TIMESTAMP_WINDOW_SECONDS
        ):
            raise AppError(
                "NODE_TIMESTAMP_INVALID",
                "节点时间戳无效",
                status_code=401,
            )
        expected = _signature(
            token,
            path=application.request_path,
            timestamp=application.auth_timestamp,
            nonce=application.auth_nonce,
            body=application.raw_body,
        )
        if not hmac.compare_digest(expected, application.auth_signature):
            raise AppError(
                "REGISTRATION_TOKEN_INVALID",
                "Token 与注册申请不匹配",
                status_code=401,
            )
        existing = await self.session.get(AccessNode, application.node_id)
        if existing is not None:
            raise AppError("NODE_ALREADY_EXISTS", "接入节点已存在", status_code=409)
        node = AccessNode(
            node_id=application.node_id,
            reported_name=application.reported_name,
            hostname=application.hostname,
            software_version=application.software_version,
            encrypted_token=self.cipher.encrypt(token),
        )
        application.status = "approved"
        self.session.add(node)
        await self.session.commit()
        await self.session.refresh(node)
        return node
