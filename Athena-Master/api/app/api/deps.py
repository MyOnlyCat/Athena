from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, Request
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
    return AuthService(
        session,
        request.app.state.settings,
        request.app.state.administrator_write_lock,
    )


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


def enforce_node_request_limit(
    request: Request,
    node_id: Annotated[str, Header(alias="X-Node-Id")],
) -> None:
    request.app.state.node_request_throttle.check_and_record(
        node_id,
        datetime.now(UTC),
    )
