from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.time import as_utc

HostTestStatus = Literal["success", "failed", "pending_trust"]
HostTestCode = Literal[
    "SSH_CONNECTED",
    "SSH_AUTH_FAILED",
    "SSH_TIMEOUT",
    "SSH_CONNECTION_FAILED",
    "SSH_HOST_KEY_UNTRUSTED",
    "SSH_HOST_KEY_CHANGED",
]
AssetLifecycleStatus = Literal["active", "retired"]


def clean_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or any(ord(character) < 32 for character in cleaned):
        raise ValueError("value must not be blank or contain control characters")
    return cleaned


class HeartbeatHost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535, strict=True)
    username: str = Field(min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=20)
    is_local: bool = Field(strict=True)
    last_test_status: HostTestStatus | None = None
    last_test_code: HostTestCode | None = None
    last_tested_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def validate_host_id(cls, value: str) -> str:
        parsed = UUID(value)
        if str(parsed) != value:
            raise ValueError("id must be a canonical UUID")
        return value

    @field_validator("name", "address", "username")
    @classmethod
    def reject_blank_or_control_characters(cls, value: str) -> str:
        return clean_text(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        cleaned = [clean_text(value) for value in values]
        if any(len(value) > 32 for value in cleaned) or len(set(cleaned)) != len(cleaned):
            raise ValueError("tags must be unique and at most 32 characters")
        return cleaned

    @field_validator("last_tested_at")
    @classmethod
    def require_utc_compatible_test_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("last_tested_at must include a timezone")
        return as_utc(value)

    @model_validator(mode="after")
    def validate_test_result(self) -> "HeartbeatHost":
        if self.last_test_status is None:
            if self.last_test_code is not None or self.last_tested_at is not None:
                raise ValueError("untested host cannot contain a test code or time")
        elif self.last_test_code is None or self.last_tested_at is None:
            raise ValueError("tested host requires a test code and time")
        allowed_codes: dict[HostTestStatus, set[HostTestCode]] = {
            "success": {"SSH_CONNECTED"},
            "pending_trust": {"SSH_HOST_KEY_UNTRUSTED"},
            "failed": {
                "SSH_AUTH_FAILED",
                "SSH_TIMEOUT",
                "SSH_CONNECTION_FAILED",
                "SSH_HOST_KEY_CHANGED",
            },
        }
        if (
            self.last_test_status is not None
            and self.last_test_code not in allowed_codes[self.last_test_status]
        ):
            raise ValueError("test status and code are inconsistent")
        return self


class HostAssetItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: str
    host_id: str
    name: str
    address: str
    port: int
    username: str
    tags: list[str]
    is_local: bool
    last_test_status: HostTestStatus | None
    last_test_code: HostTestCode | None
    last_tested_at: datetime | None
    lifecycle_status: AssetLifecycleStatus
    retired_at: datetime | None

    @field_validator("last_tested_at", "retired_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return as_utc(value) if value is not None else None


class HostAssetPage(BaseModel):
    items: list[HostAssetItem]
    page: int
    page_size: int
    total: int
