from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.registration import AccessNode
from app.schemas.heartbeat import ConnectivityStatus
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
