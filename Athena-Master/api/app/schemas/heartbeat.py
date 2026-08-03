from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.time import AwareUtcDatetime, as_utc
from app.schemas.asset import HeartbeatHost
from app.schemas.node import ManagedAccessNodeResponse

ConnectivityStatus = Literal["online", "stale", "offline"]


class HeartbeatNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=255)
    reported_at: AwareUtcDatetime

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
    hosts: list[HeartbeatHost] = Field(max_length=500)

    @model_validator(mode="after")
    def reject_duplicate_host_ids(self) -> "HeartbeatPayload":
        host_ids = [host.id for host in self.hosts]
        if len(set(host_ids)) != len(host_ids):
            raise ValueError("host ids must be unique within a snapshot")
        return self


class HeartbeatAccepted(BaseModel):
    accepted_at: datetime
    next_heartbeat_seconds: Literal[60] = 60

    @field_validator("accepted_at")
    @classmethod
    def normalize_accepted_at(cls, value: datetime) -> datetime:
        return as_utc(value)


class AccessNodeListItem(ManagedAccessNodeResponse):
    connectivity_status: ConnectivityStatus
    approved_at: datetime
    last_heartbeat_at: datetime | None

    @field_validator("approved_at", "last_heartbeat_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return as_utc(value) if value is not None else None


class AccessNodePage(BaseModel):
    items: list[AccessNodeListItem]
    page: int
    page_size: int
    total: int
