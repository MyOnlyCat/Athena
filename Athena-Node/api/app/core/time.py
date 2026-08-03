from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_rfc3339(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
