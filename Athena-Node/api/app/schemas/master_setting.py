import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.node_token import validate_node_token

_HOST_LABEL = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
MasterScheme = Literal["http", "https"]
MasterRuntimeStatus = Literal[
    "unconfigured",
    "connecting",
    "online",
    "error",
    "stopped",
]
RegistrationStatus = Literal["not_submitted", "pending"]


class MasterSettingInput(BaseModel):
    scheme: MasterScheme
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65_535)
    token: str = Field(default="", repr=False)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        host = value.strip().lower()
        if not host or any(character in host for character in "/?#@"):
            raise ValueError("invalid master host")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.rstrip(".").split(".")
            if any(not _HOST_LABEL.fullmatch(label) for label in labels):
                raise ValueError("invalid master host") from None
            host = host.rstrip(".")
        return host

    @field_validator("token")
    @classmethod
    def validate_token_length(cls, value: str) -> str:
        return validate_node_token(value)


class MasterSettingResponse(BaseModel):
    node_id: str
    node_name: str
    scheme: MasterScheme
    host: str
    port: int
    has_token: bool
    runtime_status: MasterRuntimeStatus
    registration_status: RegistrationStatus


class MasterConnectionTestResponse(BaseModel):
    status: Literal["success"] = "success"


class RegistrationApplicationResponse(BaseModel):
    status: Literal["pending"]
