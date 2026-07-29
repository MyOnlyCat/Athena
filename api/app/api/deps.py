from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.user import User
from app.services.auth import AuthService

bearer = HTTPBearer(auto_error=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_auth_service(request: Request, session: SessionDep) -> AuthService:
    return AuthService(session, request.app.state.settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_auth_context(
    auth: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> tuple[User, dict[str, Any]]:
    if credentials is None:
        raise AppError("AUTH_REQUIRED", "请先登录", status_code=401)
    return await auth.decode_access_token(credentials.credentials)


AuthContextDep = Annotated[tuple[User, dict[str, Any]], Depends(get_auth_context)]


async def get_current_user(context: AuthContextDep) -> User:
    return context[0]


CurrentUserDep = Annotated[User, Depends(get_current_user)]
