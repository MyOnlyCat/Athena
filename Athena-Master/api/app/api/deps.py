from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import session_dependency
from app.core.errors import AppError
from app.models.user import User
from app.services.auth import AuthService

bearer = HTTPBearer(auto_error=False)


async def get_session(request: Request) -> Any:
    async for session in session_dependency(request.app.state.session_factory):
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_auth_service(request: Request, session: SessionDep) -> AuthService:
    return AuthService(session, request.app.state.settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_auth_context(
    request: Request,
    auth: AuthServiceDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> tuple[User, dict[str, Any]]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("AUTH_REQUIRED", "请先登录", status_code=401)
    context = await auth.decode_access_token(credentials.credentials)
    request.state.user_id = context[0].id
    return context


AuthContextDep = Annotated[tuple[User, dict[str, Any]], Depends(get_auth_context)]


async def get_current_user(context: AuthContextDep) -> User:
    return context[0]


CurrentUserDep = Annotated[User, Depends(get_current_user)]
