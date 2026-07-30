import re
from typing import cast

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.user import User


class UserService:
    def __init__(self, session: AsyncSession, password_hash: PasswordHash) -> None:
        self.session = session
        self.password_hash = password_hash

    async def get_by_normalized_username(self, username: str) -> User | None:
        normalized = username.strip().casefold()
        return cast(
            User | None,
            await self.session.scalar(
                select(User).where(User.normalized_username == normalized)
            ),
        )

    async def create_bootstrap_admin(self, username: str, password: str) -> User:
        username = username.strip()
        if not username:
            raise AppError("INVALID_USERNAME", "初始化管理员用户名不能为空", status_code=422)
        if (
            len(password) < 12
            or len(password) > 128
            or not re.search(r"[A-Za-z]", password)
            or not re.search(r"\d", password)
            or password.casefold() == username.casefold()
        ):
            raise AppError(
                "INVALID_PASSWORD",
                "初始化管理员密码须为 12–128 个字符，且同时包含字母和数字",
                status_code=422,
            )

        user = User(
            username=username,
            normalized_username=username.casefold(),
            password_hash=self.password_hash.hash(password),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
