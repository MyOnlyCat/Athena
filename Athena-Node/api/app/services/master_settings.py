from dataclasses import dataclass, field
from typing import cast
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.node_token import validate_node_token
from app.models.master_setting import MasterSetting
from app.schemas.master_setting import MasterScheme, MasterSettingInput
from app.services.crypto import CredentialCipher


@dataclass(frozen=True)
class MasterConfig:
    scheme: MasterScheme
    host: str
    port: int
    token: str = field(repr=False)

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}"


class MasterSettingsService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        cipher: CredentialCipher,
    ) -> None:
        self.session = session
        self.settings = settings
        self.cipher = cipher

    def environment_config(self) -> MasterConfig:
        value = self.settings.master_node_url.strip()
        token = validate_node_token(self.settings.node_token)
        if not value:
            return MasterConfig("https", "", 443, token)
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or parsed.hostname is None:
            return MasterConfig("https", "", 443, token)
        return MasterConfig(
            cast(MasterScheme, scheme),
            parsed.hostname.lower(),
            parsed.port or (443 if scheme == "https" else 80),
            token,
        )

    async def get_row(self) -> MasterSetting | None:
        return await self.session.get(MasterSetting, 1)

    async def get_effective(self) -> MasterConfig:
        row = await self.get_row()
        if row is None:
            return self.environment_config()
        token = self.cipher.decrypt(row.encrypted_token) if row.encrypted_token else ""
        return MasterConfig(cast(MasterScheme, row.scheme), row.host, row.port, token)

    async def resolve(self, data: MasterSettingInput) -> MasterConfig:
        current = await self.get_effective()
        token = data.token if data.token else current.token
        return MasterConfig(data.scheme, data.host, data.port, token)

    async def save(
        self,
        data: MasterSettingInput,
        config: MasterConfig,
    ) -> MasterSetting:
        row = await self.get_row()
        if row is None:
            row = MasterSetting(id=1)
            self.session.add(row)
        row.scheme = data.scheme
        row.host = data.host
        row.port = data.port
        if data.token:
            row.encrypted_token = self.cipher.encrypt(data.token)
        elif row.encrypted_token is None and config.token:
            row.encrypted_token = self.cipher.encrypt(config.token)
        await self.session.flush()
        return row

    async def set_registration_pending(self) -> None:
        row = await self.get_row()
        if row is None:
            raise RuntimeError("master settings must be saved before registration")
        row.registration_status = "pending"
        await self.session.commit()
