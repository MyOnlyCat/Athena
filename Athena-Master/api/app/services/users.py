import re
from asyncio import Lock
from typing import cast

from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.user import User
from app.schemas.user import UserCreate
from app.services.audit import AuditedAction, commit_with_audit


def validate_admin_password(username: str, password: str) -> None:
    if (
        len(password) < 12
        or len(password) > 128
        or not re.search(r"[A-Za-z]", password)
        or not re.search(r"\d", password)
        or password.casefold() == username.casefold()
    ):
        raise AppError(
            "INVALID_PASSWORD",
            "密码须为 12–128 个字符，且同时包含字母和数字，并且不能与用户名相同",
            status_code=422,
        )


class UserService:
    def __init__(
        self,
        session: AsyncSession,
        password_hash: PasswordHash,
        write_lock: Lock,
    ) -> None:
        self.session = session
        self.password_hash = password_hash
        self.write_lock = write_lock

    async def get_by_normalized_username(self, username: str) -> User | None:
        normalized = username.strip().casefold()
        return cast(
            User | None,
            await self.session.scalar(select(User).where(User.normalized_username == normalized)),
        )

    async def get(self, user_id: str) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise AppError("ADMIN_NOT_FOUND", "管理员不存在", status_code=404)
        return user

    async def list_page(self, page: int, page_size: int) -> tuple[list[User], int]:
        total = int(await self.session.scalar(select(func.count()).select_from(User)) or 0)
        users = list(
            (
                await self.session.scalars(
                    select(User)
                    .order_by(User.created_at, User.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return users, total

    async def create(
        self,
        data: UserCreate,
        audit: AuditedAction | None = None,
    ) -> User:
        async with self.write_lock:
            return await self._create(data, audit)

    async def _create(
        self,
        data: UserCreate,
        audit: AuditedAction | None = None,
    ) -> User:
        if await self.get_by_normalized_username(data.username):
            raise AppError("USERNAME_EXISTS", "用户名已存在", status_code=409)
        validate_admin_password(data.username, data.password)
        user = User(
            username=data.username,
            normalized_username=data.username.casefold(),
            password_hash=self.password_hash.hash(data.password),
        )
        self.session.add(user)
        if audit is not None:
            audit.set_target(user.normalized_username, user.username)
        await commit_with_audit(self.session, audit)
        await self.session.refresh(user)
        return user

    async def set_active(
        self,
        user_id: str,
        is_active: bool,
        actor_id: str,
        audit: AuditedAction | None = None,
    ) -> User:
        async with self.write_lock:
            return await self._set_active(user_id, is_active, actor_id, audit)

    async def _set_active(
        self,
        user_id: str,
        is_active: bool,
        actor_id: str,
        audit: AuditedAction | None = None,
    ) -> User:
        user = await self.get(user_id)
        if audit is not None:
            audit.set_target(user.id, user.username)
        if not is_active and user.id == actor_id:
            raise AppError(
                "CANNOT_DISABLE_SELF",
                "不能禁用当前登录管理员",
                status_code=409,
            )
        if not is_active and user.is_active:
            active_count = int(
                await self.session.scalar(
                    select(func.count()).select_from(User).where(User.is_active.is_(True))
                )
                or 0
            )
            if active_count <= 1:
                raise AppError(
                    "LAST_ACTIVE_ADMIN",
                    "不能禁用最后一个可用管理员",
                    status_code=409,
                )
            user.auth_version += 1
        user.is_active = is_active
        await commit_with_audit(self.session, audit)
        await self.session.refresh(user)
        return user

    async def reset_password(
        self,
        user_id: str,
        password: str,
        audit: AuditedAction | None = None,
    ) -> None:
        async with self.write_lock:
            await self._reset_password(user_id, password, audit)

    async def _reset_password(
        self,
        user_id: str,
        password: str,
        audit: AuditedAction | None = None,
    ) -> None:
        user = await self.get(user_id)
        if audit is not None:
            audit.set_target(user.id, user.username)
        validate_admin_password(user.username, password)
        user.password_hash = self.password_hash.hash(password)
        user.auth_version += 1
        await commit_with_audit(self.session, audit)

    async def create_bootstrap_admin(self, username: str, password: str) -> User:
        username = username.strip()
        if not username:
            raise AppError("INVALID_USERNAME", "初始化管理员用户名不能为空", status_code=422)
        validate_admin_password(username, password)

        user = User(
            username=username,
            normalized_username=username.casefold(),
            password_hash=self.password_hash.hash(password),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
