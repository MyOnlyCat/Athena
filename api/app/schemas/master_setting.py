import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_HOST_LABEL = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
MasterScheme = Literal["http", "https"]
MasterRuntimeStatus = Literal[
    "unconfigured",
    "connecting",
    "online",
    "error",
    "stopped",
]


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


class MasterSettingResponse(BaseModel):
    scheme: MasterScheme
    host: str
    port: int
    has_token: bool
    runtime_status: MasterRuntimeStatus


class MasterConnectionTestResponse(BaseModel):
    status: Literal["success"] = "success"
