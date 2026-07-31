from datetime import datetime

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.asset import HostAsset
from app.models.registration import AccessNode
from app.schemas.asset import HeartbeatHost, HostTestStatus

MAX_ACTIVE_ASSETS = 10_000


class AssetSnapshotService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace(
        self,
        *,
        node_id: str,
        hosts: list[HeartbeatHost],
        received_at: datetime,
    ) -> None:
        active_elsewhere = int(
            await self.session.scalar(
                select(func.count())
                .select_from(HostAsset)
                .where(HostAsset.node_id != node_id, HostAsset.retired_at.is_(None))
            )
            or 0
        )
        if active_elsewhere + len(hosts) > MAX_ACTIVE_ASSETS:
            raise AppError(
                "ASSET_CAPACITY_EXCEEDED",
                "在管主机资产数量超过 10000 条限制",
                status_code=422,
            )

        existing = {
            asset.host_id: asset
            for asset in (
                await self.session.scalars(
                    select(HostAsset).where(HostAsset.node_id == node_id)
                )
            ).all()
        }
        present_ids: set[str] = set()
        for reported in hosts:
            present_ids.add(reported.id)
            asset = existing.get(reported.id)
            if asset is None:
                asset = HostAsset(node_id=node_id, host_id=reported.id)
                self.session.add(asset)
            for field, value in reported.model_dump().items():
                setattr(asset, "host_id" if field == "id" else field, value)
            asset.retired_at = None

        for host_id, asset in existing.items():
            if host_id not in present_ids and asset.retired_at is None:
                asset.retired_at = received_at


class HostAssetQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_page(
        self,
        *,
        node_id: str,
        page: int,
        page_size: int,
        search: str | None,
        lifecycle_status: str | None,
        detection_status: HostTestStatus | None,
        tag: str | None,
    ) -> tuple[list[HostAsset], int]:
        if await self.session.get(AccessNode, node_id) is None:
            raise AppError("NODE_NOT_FOUND", "接入节点不存在", status_code=404)

        filters = [HostAsset.node_id == node_id]
        if search:
            pattern = f"%{search.strip()}%"
            filters.append(or_(HostAsset.name.ilike(pattern), HostAsset.address.ilike(pattern)))
        if lifecycle_status == "active":
            filters.append(HostAsset.retired_at.is_(None))
        elif lifecycle_status == "retired":
            filters.append(HostAsset.retired_at.is_not(None))
        if detection_status:
            filters.append(HostAsset.last_test_status == detection_status)
        if tag:
            filters.append(cast(HostAsset.tags, String).contains(f'"{tag.strip()}"'))

        query = select(HostAsset).where(*filters)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(HostAsset).where(*filters)
            )
            or 0
        )
        assets = list(
            (
                await self.session.scalars(
                    query.order_by(HostAsset.name.asc(), HostAsset.host_id.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return assets, total
