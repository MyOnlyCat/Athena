from asyncio import Lock
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.user import RevokedToken, User
from app.services.users import UserService


class LoginThrottle:
    def __init__(self, max_failures: int = 5, lock_minutes: int = 15) -> None:
        self.max_failures = max_failures
        self.lock_duration = timedelta(minutes=lock_minutes)
        self._failures: dict[tuple[str, str], tuple[int, datetime | None]] = {}

    def ensure_allowed(self, username: str, source_ip: str) -> None:
        key = (username.strip().casefold(), source_ip)
        _, locked_until = self._failures.get(key, (0, None))
        now = datetime.now(UTC)
        if locked_until is not None and locked_until > now:
            raise AppError(
                "LOGIN_LOCKED",
                "登录失败次数过多，请稍后重试",
                status_code=429,
            )
        if locked_until is not None:
            self._failures.pop(key, None)

    def record_failure(self, username: str, source_ip: str) -> None:
        key = (username.strip().casefold(), source_ip)
        count, _ = self._failures.get(key, (0, None))
        count += 1
        locked_until = (
            datetime.now(UTC) + self.lock_duration if count >= self.max_failures else None
        )
        self._failures[key] = (count, locked_until)

    def reset(self, username: str, source_ip: str) -> None:
        self._failures.pop((username.strip().casefold(), source_ip), None)


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        administrator_write_lock: Lock,
    ) -> None:
        self.session = session
        self.settings = settings
        self.password_hash = PasswordHash.recommended()
        self.users = UserService(session, self.password_hash, administrator_write_lock)

    async def authenticate(self, username: str, password: str) -> User:
        user = await self.users.get_by_normalized_username(username)
        if user is None or not self.password_hash.verify(password, user.password_hash):
            raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", status_code=401)
        if not user.is_active:
            raise AppError("USER_DISABLED", "用户已被禁用", status_code=403)
        user.last_login_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    def issue_access_token(self, user: User) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": user.id,
                "jti": str(uuid4()),
                "auth_version": user.auth_version,
                "iat": now,
                "exp": now + timedelta(minutes=self.settings.access_token_minutes),
            },
            self.settings.jwt_secret,
            algorithm="HS256",
        )

    async def decode_access_token(self, token: str) -> tuple[User, dict[str, Any]]:
        try:
            payload = jwt.decode(token, self.settings.jwt_secret, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise AppError("INVALID_TOKEN", "登录凭证无效", status_code=401) from exc
        jti = str(payload.get("jti", ""))
        if await self.session.get(RevokedToken, jti):
            raise AppError("TOKEN_REVOKED", "登录凭证已失效", status_code=401)
        user = await self.session.get(User, str(payload.get("sub", "")))
        if user is None:
            raise AppError("INVALID_TOKEN", "登录凭证无效", status_code=401)
        if payload.get("auth_version") != user.auth_version:
            raise AppError("TOKEN_REVOKED", "登录凭证已失效", status_code=401)
        if not user.is_active:
            raise AppError("USER_DISABLED", "用户已被禁用", status_code=403)
        return user, payload

    async def revoke(self, payload: dict[str, Any]) -> None:
        expires = datetime.fromtimestamp(float(payload["exp"]), UTC)
        self.session.add(RevokedToken(jti=str(payload["jti"]), expires_at=expires))
        await self.session.commit()
