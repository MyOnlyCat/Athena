import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RegistrationApplicationStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "expired",
    "restored",
]


class RegistrationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    reported_name: str = Field(min_length=1, max_length=100)
    hostname: str = Field(min_length=1, max_length=255)
    software_version: str = Field(min_length=1, max_length=64)

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("node_id must be a canonical UUIDv7")
        return value

    @field_validator("reported_name", "hostname", "software_version")
    @classmethod
    def reject_blank_or_control_characters(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("value must not be blank or contain control characters")
        return cleaned


class RegistrationSubmitted(BaseModel):
    status: Literal["pending"]


class RegistrationStatusResponse(BaseModel):
    status: RegistrationApplicationStatus


class RegistrationApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_id: str
    reported_name: str
    hostname: str
    software_version: str
    status: RegistrationApplicationStatus
    rejection_reason: str | None = None
    identity_verified: bool = False
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


class RegistrationApplicationPage(BaseModel):
    items: list[RegistrationApplicationResponse]
    page: int
    page_size: int
    total: int


class RegistrationApproval(BaseModel):
    token: str = Field(min_length=32, max_length=256, repr=False)


class RegistrationRejection(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AccessNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: str
    reported_name: str
    hostname: str
    software_version: str
    management_status: str
    approved_at: datetime

    @field_validator("approved_at")
    @classmethod
    def normalize_approved_at(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


NONCE_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
