from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.registration import AccessNode
from app.schemas.heartbeat import ConnectivityStatus
from app.schemas.node import ManagementStatus, MutableManagementStatus
from app.services.crypto import CredentialCipher, node_token_fingerprint
from app.services.node_status import ONLINE_WINDOW_SECONDS, STALE_WINDOW_SECONDS


class AccessNodeQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        management_status: ManagementStatus | None,
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
                    AccessNode.display_name.ilike(pattern),
                    AccessNode.hostname.ilike(pattern),
                    AccessNode.software_version.ilike(pattern),
                )
            )
        if management_status is not None:
            conditions.append(AccessNode.management_status == management_status)
        if requested_connectivity is not None:
            online_cutoff = now - timedelta(seconds=ONLINE_WINDOW_SECONDS)
            offline_cutoff = now - timedelta(seconds=STALE_WINDOW_SECONDS)
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


class AccessNodeManagementService:
    def __init__(self, session: AsyncSession, credential_key: str) -> None:
        self.session = session
        self.credential_key = credential_key
        self.cipher = CredentialCipher(credential_key)

    async def _get(self, node_id: str) -> AccessNode:
        node = await self.session.get(AccessNode, node_id)
        if node is None:
            raise AppError("NODE_NOT_FOUND", "接入节点不存在", status_code=404)
        return node

    async def update_info(
        self,
        node_id: str,
        *,
        display_name: str | None,
        notes: str | None,
        management_tags: list[str],
    ) -> AccessNode:
        node = await self._get(node_id)
        node.display_name = display_name
        node.notes = notes
        node.management_tags = management_tags
        await self.session.commit()
        await self.session.refresh(node)
        return node

    async def set_status(
        self,
        node_id: str,
        *,
        management_status: MutableManagementStatus,
        reason: str | None,
    ) -> AccessNode:
        node = await self._get(node_id)
        node.management_status = management_status
        node.disable_reason = reason if management_status == "disabled" else None
        await self.session.commit()
        await self.session.refresh(node)
        return node

    async def rotate_token(self, node_id: str, token: str) -> AccessNode:
        node = await self._get(node_id)
        fingerprint = node_token_fingerprint(self.credential_key, token)
        if node.token_fingerprint == fingerprint:
            raise AppError(
                "NODE_TOKEN_UNCHANGED",
                "新 Token 必须与当前 Token 不同",
                status_code=409,
            )
        owner = await self.session.scalar(
            select(AccessNode.node_id).where(
                AccessNode.token_fingerprint == fingerprint,
                AccessNode.node_id != node_id,
            )
        )
        if owner is not None:
            raise AppError(
                "NODE_TOKEN_DUPLICATE",
                "Token 已被其他接入节点使用",
                status_code=409,
            )
        node.encrypted_token = self.cipher.encrypt(token)
        node.token_fingerprint = fingerprint
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise AppError(
                "NODE_TOKEN_DUPLICATE",
                "Token 已被其他接入节点使用",
                status_code=409,
            ) from None
        await self.session.refresh(node)
        return node
