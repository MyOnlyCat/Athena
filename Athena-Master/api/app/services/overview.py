from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import HostAsset
from app.models.registration import AccessNode, RegistrationApplication
from app.schemas.overview import (
    OverviewAssetCounts,
    OverviewNodeCounts,
    OverviewResponse,
)
from app.services.node_status import connectivity_filters


class OverviewQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, now: datetime) -> OverviewResponse:
        connectivity = connectivity_filters(now)

        node_row = (
            await self.session.execute(
                select(
                    func.count(AccessNode.node_id),
                    func.count().filter(AccessNode.management_status == "pending"),
                    func.count().filter(AccessNode.management_status == "active"),
                    func.count().filter(AccessNode.management_status == "disabled"),
                    func.count().filter(AccessNode.management_status == "rejected"),
                    func.count().filter(connectivity["online"]),
                    func.count().filter(connectivity["stale"]),
                    func.count().filter(connectivity["offline"]),
                )
            )
        ).one()
        latest_applications = select(
            RegistrationApplication.node_id.label("node_id"),
            RegistrationApplication.status.label("status"),
            func.row_number()
            .over(
                partition_by=RegistrationApplication.node_id,
                order_by=(
                    RegistrationApplication.received_at.desc(),
                    RegistrationApplication.id.desc(),
                ),
            )
            .label("recency"),
        ).subquery()
        has_formal_node = exists(
            select(AccessNode.node_id).where(
                AccessNode.node_id == latest_applications.c.node_id
            )
        )
        application_row = (
            await self.session.execute(
                select(
                    func.count().filter(latest_applications.c.status == "pending"),
                    func.count().filter(latest_applications.c.status == "rejected"),
                )
                .select_from(latest_applications)
                .where(latest_applications.c.recency == 1, ~has_formal_node)
            )
        ).one()
        asset_row = (
            await self.session.execute(
                select(
                    func.count(HostAsset.host_id),
                    func.count().filter(
                        HostAsset.last_test_status == "failed",
                        connectivity["online"],
                    ),
                    func.count().filter(connectivity["offline"]),
                )
                .join(AccessNode, AccessNode.node_id == HostAsset.node_id)
                .where(HostAsset.retired_at.is_(None))
            )
        ).one()

        (
            formal_total,
            formal_pending,
            active,
            disabled,
            formal_rejected,
            online,
            stale,
            offline,
        ) = (int(value or 0) for value in node_row)
        pending_applications, rejected_applications = (
            int(value or 0) for value in application_row
        )
        active_assets, abnormal_assets, unknown_assets = (
            int(value or 0) for value in asset_row
        )
        pending = formal_pending + pending_applications
        rejected = formal_rejected + rejected_applications
        return OverviewResponse(
            nodes=OverviewNodeCounts(
                total=formal_total + pending_applications + rejected_applications,
                pending=pending,
                active=active,
                disabled=disabled,
                rejected=rejected,
                online=online,
                stale=stale,
                offline=offline,
            ),
            assets=OverviewAssetCounts(
                active=active_assets,
                abnormal=abnormal_assets,
                unknown=unknown_assets,
            ),
        )
