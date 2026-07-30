from pydantic import BaseModel, Field, field_validator


class ArtifactSpec(BaseModel):
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("制品名称不合法")
        return value


class TargetSpec(BaseModel):
    ip: str = Field(min_length=1, max_length=255)
    directory: str
    command: str = Field(min_length=1)

    @field_validator("directory")
    @classmethod
    def absolute_directory(cls, value: str) -> str:
        if not value.startswith("/") or "\x00" in value:
            raise ValueError("目标目录必须是绝对路径")
        return value


class ClaimedTask(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    artifact: ArtifactSpec
    targets: list[TargetSpec] = Field(min_length=1)

