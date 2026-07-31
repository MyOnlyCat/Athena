from datetime import UTC, datetime
from typing import Any, cast

import asyncssh
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.host import Host
from app.schemas.host import HostCreate, HostUpdate
from app.services.crypto import CredentialCipher
from app.services.ssh import (
    HostConnection,
    SSHClientProtocol,
    SSHHostKeyChanged,
)


class HostService:
    def __init__(
        self,
        session: AsyncSession,
        cipher: CredentialCipher,
        ssh_client: SSHClientProtocol,
    ) -> None:
        self.session = session
        self.cipher = cipher
        self.ssh_client = ssh_client

    async def list(self) -> list[Host]:
        return list((await self.session.scalars(select(Host).order_by(Host.name))).all())

    async def get(self, host_id: str) -> Host:
        host = await self.session.get(Host, host_id)
        if host is None:
            raise AppError("HOST_NOT_FOUND", "主机不存在", status_code=404)
        return host

    async def _ensure_local_available(self, host_id: str | None = None) -> None:
        query = select(Host).where(Host.is_local.is_(True))
        if host_id:
            query = query.where(Host.id != host_id)
        if await self.session.scalar(query):
            raise AppError("LOCAL_HOST_EXISTS", "当前节点主机已存在", status_code=409)

    async def create(self, data: HostCreate) -> Host:
        if data.is_local:
            await self._ensure_local_available()
        host = Host(
            **data.model_dump(exclude={"password"}),
            encrypted_password=self.cipher.encrypt(data.password),
        )
        self.session.add(host)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError("HOST_ADDRESS_EXISTS", "主机地址已存在", status_code=409) from exc
        await self.session.refresh(host)
        return host

    async def update(self, host_id: str, data: HostUpdate) -> Host:
        host = await self.get(host_id)
        if data.is_local and not host.is_local:
            await self._ensure_local_available(host_id)
        endpoint_changed = host.address != data.address or host.port != data.port
        for key, value in data.model_dump(exclude={"password"}).items():
            setattr(host, key, value)
        if endpoint_changed:
            host.host_key_fingerprint = None
        if data.password is not None:
            host.encrypted_password = self.cipher.encrypt(data.password)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError("HOST_ADDRESS_EXISTS", "主机地址已存在", status_code=409) from exc
        await self.session.refresh(host)
        return host

    async def delete(self, host_id: str) -> None:
        host = await self.get(host_id)
        await self.session.delete(host)
        await self.session.commit()

    async def test_connection(self, host_id: str) -> dict[str, Any]:
        host = await self.get(host_id)
        connection = HostConnection(
            address=host.address,
            port=host.port,
            username=host.username,
            password=self.cipher.decrypt(host.encrypted_password),
            host_key_fingerprint=host.host_key_fingerprint,
        )
        try:
            result = await self.ssh_client.test_connection(connection)
        except SSHHostKeyChanged as exc:
            result = {
                "status": "failed",
                "code": "SSH_HOST_KEY_CHANGED",
                "message": "SSH 主机指纹已变更",
                "fingerprint": exc.actual,
            }
        except asyncssh.HostKeyNotVerifiable:
            result = {
                "status": "failed",
                "code": "SSH_HOST_KEY_CHANGED",
                "message": "SSH 主机指纹已变更",
            }
        except asyncssh.PermissionDenied:
            result = {"status": "failed", "code": "SSH_AUTH_FAILED", "message": "SSH 认证失败"}
        except TimeoutError:
            result = {"status": "failed", "code": "SSH_TIMEOUT", "message": "SSH 连接超时"}
        except OSError:
            result = {
                "status": "failed",
                "code": "SSH_CONNECTION_FAILED",
                "message": "SSH 连接失败",
            }
        fingerprint = cast(str | None, result.get("fingerprint"))
        if fingerprint and host.host_key_fingerprint is None:
            result.update(
                status="pending_trust",
                code="SSH_HOST_KEY_UNTRUSTED",
                message="请确认主机指纹",
            )
        elif fingerprint and host.host_key_fingerprint != fingerprint:
            result.update(
                status="failed",
                code="SSH_HOST_KEY_CHANGED",
                message="SSH 主机指纹已变化",
            )
        elif fingerprint:
            result.update(status="success", code="SSH_CONNECTED", message="SSH 连接成功")
        host.last_test_status = str(result["status"])
        host.last_test_code = str(result["code"])
        host.last_test_message = str(result["message"])
        host.last_tested_at = datetime.now(UTC)
        await self.session.commit()
        return result

    async def trust_fingerprint(self, host_id: str, fingerprint: str) -> Host:
        host = await self.get(host_id)
        host.host_key_fingerprint = fingerprint
        await self.session.commit()
        await self.session.refresh(host)
        return host
