from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if any(ord(character) < 32 for character in cleaned):
        raise ValueError("value must not contain control characters")
    return cleaned


class NodeManagementInfoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)
    management_tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("display_name", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("management_tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        cleaned = [_optional_text(value) for value in values]
        if any(value is None or len(value) > 32 for value in cleaned):
            raise ValueError("tags must contain 1 to 32 characters")
        normalized = [value for value in cleaned if value is not None]
        if len(set(normalized)) != len(normalized):
            raise ValueError("tags must be unique")
        return normalized


class NodeStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    management_status: Literal["active", "disabled"]
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        return _optional_text(value)


class NodeTokenRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=256, repr=False)


class ManagedAccessNodeResponse(BaseModel):
    node_id: str
    reported_name: str
    display_name: str | None
    effective_name: str
    hostname: str
    software_version: str
    management_status: str
    notes: str | None
    management_tags: list[str]
    disable_reason: str | None
