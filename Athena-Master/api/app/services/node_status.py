from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from app.core.time import as_utc
from app.models.registration import AccessNode
from app.schemas.heartbeat import ConnectivityStatus

ONLINE_WINDOW_SECONDS = 120
STALE_WINDOW_SECONDS = 300


def connectivity_filters(now: datetime) -> dict[ConnectivityStatus, ColumnElement[bool]]:
    online_cutoff = now - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    offline_cutoff = now - timedelta(seconds=STALE_WINDOW_SECONDS)
    return {
        "online": AccessNode.last_heartbeat_at > online_cutoff,
        "stale": (
            (AccessNode.last_heartbeat_at <= online_cutoff)
            & (AccessNode.last_heartbeat_at >= offline_cutoff)
        ),
        "offline": or_(
            AccessNode.last_heartbeat_at.is_(None),
            AccessNode.last_heartbeat_at < offline_cutoff,
        ),
    }


def connectivity_status(
    last_heartbeat_at: datetime | None,
    now: datetime,
) -> ConnectivityStatus:
    if last_heartbeat_at is None:
        return "offline"
    age = as_utc(now) - as_utc(last_heartbeat_at)
    if age < timedelta(seconds=ONLINE_WINDOW_SECONDS):
        return "online"
    if age <= timedelta(seconds=STALE_WINDOW_SECONDS):
        return "stale"
    return "offline"
