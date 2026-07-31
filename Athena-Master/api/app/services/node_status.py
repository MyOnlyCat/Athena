from datetime import datetime, timedelta

from app.core.time import as_utc
from app.schemas.heartbeat import ConnectivityStatus

ONLINE_WINDOW_SECONDS = 120
STALE_WINDOW_SECONDS = 300


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
