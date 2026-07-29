from typing import cast

from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.user import User
from app.schemas.user import UserCreate


def normalize_username(username: str) -> str:
    return username.strip().casefold()


class UserService:
    def __init__(self, session: AsyncSession, password_hash: PasswordHash) -> None:
        self.session = session
        self.password_hash = password_hash

    async def get_by_normalized_username(self, username: str) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(
                select(User).where(User.normalized_username == normalize_username(username))
            ),
        )

    async def get(self, user_id: str) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise AppError("USER_NOT_FOUND", "用户不存在", status_code=404)
        return user

    async def list(self) -> list[User]:
        return list((await self.session.scalars(select(User).order_by(User.created_at))).all())

    async def create(self, data: UserCreate) -> User:
        if await self.get_by_normalized_username(data.username):
            raise AppError("USERNAME_EXISTS", "用户名已存在", status_code=409)
        user = User(
            username=data.username.strip(),
            normalized_username=normalize_username(data.username),
            password_hash=self.password_hash.hash(data.password),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def set_active(self, user_id: str, is_active: bool, actor_id: str) -> User:
        user = await self.get(user_id)
        if not is_active and user.id == actor_id:
            raise AppError("CANNOT_DISABLE_SELF", "不能禁用当前登录用户", status_code=409)
        if not is_active:
            active_count = await self.session.scalar(
                select(func.count()).select_from(User).where(User.is_active.is_(True))
            )
            if active_count is not None and active_count <= 1:
                raise AppError(
                    "LAST_ACTIVE_USER",
                    "不能禁用最后一个可用用户",
                    status_code=409,
                )
        user.is_active = is_active
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def reset_password(self, user_id: str, password: str) -> None:
        user = await self.get(user_id)
        user.password_hash = self.password_hash.hash(password)
        await self.session.commit()
