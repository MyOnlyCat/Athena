from fastapi import APIRouter, Response, status
from pwdlib import PasswordHash

from app.api.deps import CurrentUserDep, SessionDep
from app.models.user import User
from app.schemas.user import PasswordReset, UserCreate, UserResponse, UserStatusUpdate
from app.services.users import UserService

router = APIRouter(prefix="/users", tags=["users"])


def service(session: SessionDep) -> UserService:
    return UserService(session, PasswordHash.recommended())


@router.get("", response_model=list[UserResponse])
async def list_users(session: SessionDep, _: CurrentUserDep) -> list[User]:
    return await service(session).list()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    session: SessionDep,
    _: CurrentUserDep,
) -> User:
    return await service(session).create(data)


@router.patch("/{user_id}/status", response_model=UserResponse)
async def set_user_status(
    user_id: str,
    data: UserStatusUpdate,
    session: SessionDep,
    actor: CurrentUserDep,
) -> User:
    return await service(session).set_active(user_id, data.is_active, actor.id)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: str,
    data: PasswordReset,
    session: SessionDep,
    _: CurrentUserDep,
) -> Response:
    await service(session).reset_password(user_id, data.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

