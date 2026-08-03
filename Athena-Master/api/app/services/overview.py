from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import HostAsset
from app.models.registration import AccessNode, RegistrationApplication
from app.schemas.overview import (
    OverviewAssetCounts,
    OverviewNodeCounts,
    OverviewResponse,
)
from app.services.node_status import ONLINE_WINDOW_SECONDS, STALE_WINDOW_SECONDS


class OverviewQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, now: datetime) -> OverviewResponse:
        online_cutoff = now - timedelta(seconds=ONLINE_WINDOW_SECONDS)
        offline_cutoff = now - timedelta(seconds=STALE_WINDOW_SECONDS)

        node_row = (
            await self.session.execute(
                select(
                    func.count(AccessNode.node_id),
                    func.count().filter(AccessNode.management_status == "pending"),
                    func.count().filter(AccessNode.management_status == "active"),
                    func.count().filter(AccessNode.management_status == "disabled"),
                    func.count().filter(AccessNode.management_status == "rejected"),
                    func.count().filter(AccessNode.last_heartbeat_at > online_cutoff),
                    func.count().filter(
                        AccessNode.last_heartbeat_at <= online_cutoff,
                        AccessNode.last_heartbeat_at >= offline_cutoff,
                    ),
                    func.count().filter(
                        or_(
                            AccessNode.last_heartbeat_at.is_(None),
                            AccessNode.last_heartbeat_at < offline_cutoff,
                        )
                    ),
                )
            )
        ).one()
        application_row = (
            await self.session.execute(
                select(
                    func.count().filter(RegistrationApplication.status == "pending"),
                    func.count().filter(RegistrationApplication.status == "rejected"),
                )
            )
        ).one()
        asset_row = (
            await self.session.execute(
                select(
                    func.count(HostAsset.host_id),
                    func.count().filter(
                        HostAsset.last_test_status == "failed",
                        AccessNode.last_heartbeat_at > online_cutoff,
                    ),
                    func.count().filter(
                        or_(
                            AccessNode.last_heartbeat_at.is_(None),
                            AccessNode.last_heartbeat_at < offline_cutoff,
                        )
                    ),
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
