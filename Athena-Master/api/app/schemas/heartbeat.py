from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ConnectivityStatus = Literal["online", "stale", "offline"]
ManagementStatus = Literal["active", "disabled", "rejected", "pending"]


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


class HeartbeatNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    reported_at: datetime

    @field_validator("id")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("id must be a canonical UUIDv7")
        return value

    @field_validator("name", "version", "hostname")
    @classmethod
    def reject_blank_or_control_characters(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("value must not be blank or contain control characters")
        return cleaned


class HeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: str = Field(min_length=1, max_length=16)
    node: HeartbeatNode
    hosts: list[dict[str, Any]]


class HeartbeatAccepted(BaseModel):
    accepted_at: datetime
    next_heartbeat_seconds: Literal[60] = 60

    @field_validator("accepted_at")
    @classmethod
    def normalize_accepted_at(cls, value: datetime) -> datetime:
        return utc(value)


class AccessNodeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: str
    reported_name: str
    hostname: str
    software_version: str
    management_status: ManagementStatus
    connectivity_status: ConnectivityStatus
    approved_at: datetime
    last_heartbeat_at: datetime | None

    @field_validator("approved_at", "last_heartbeat_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None


class AccessNodePage(BaseModel):
    items: list[AccessNodeListItem]
    page: int
    page_size: int
    total: int
