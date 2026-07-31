from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

HostTestCode = Literal[
    "SSH_CONNECTED",
    "SSH_AUTH_FAILED",
    "SSH_TIMEOUT",
    "SSH_CONNECTION_FAILED",
    "SSH_HOST_KEY_UNTRUSTED",
    "SSH_HOST_KEY_CHANGED",
]


class HostBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list)
    is_local: bool = False

    @field_validator("name", "address", "username")
    @classmethod
    def strip_required(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("字段不能为空")
        return result


class HostCreate(HostBase):
    password: str = Field(min_length=1, max_length=512)


class HostUpdate(HostBase):
    password: str | None = Field(default=None, min_length=1, max_length=512)


class HostResponse(HostBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    host_key_fingerprint: str | None
    last_test_status: str | None
    last_test_code: HostTestCode | None
    last_test_message: str | None
    last_tested_at: datetime | None
    created_at: datetime
    encrypted_password: str = Field(exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_password(self) -> bool:
        return bool(self.encrypted_password)


class FingerprintTrust(BaseModel):
    fingerprint: str = Field(pattern=r"^SHA256:")


class SSHTestResponse(BaseModel):
    status: str
    code: HostTestCode
    message: str
    fingerprint: str | None = None


class HostProbeSettingInput(BaseModel):
    interval_minutes: int = Field(ge=1, le=1440)


class HostProbeSettingResponse(HostProbeSettingInput):
    model_config = ConfigDict(from_attributes=True)
