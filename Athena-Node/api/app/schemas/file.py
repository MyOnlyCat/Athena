from datetime import datetime

from pydantic import BaseModel, field_validator


def validate_remote_path(value: str) -> str:
    if "\x00" in value:
        raise ValueError("路径包含非法字符")
    if not value.startswith("/"):
        raise ValueError("必须使用绝对路径")
    return value


class DirectoryCreate(BaseModel):
    path: str

    _validate = field_validator("path")(validate_remote_path)


class FileRename(BaseModel):
    source: str
    destination: str

    _validate = field_validator("source", "destination")(validate_remote_path)


class FileDelete(BaseModel):
    path: str
    recursive: bool = False

    _validate = field_validator("path")(validate_remote_path)


class FileEntry(BaseModel):
    name: str
    path: str
    type: str
    size: int
    modified_at: datetime | None
    permissions: str


class FileListResponse(BaseModel):
    path: str
    entries: list[FileEntry]

