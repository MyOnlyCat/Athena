from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AuthenticatedAuditDep, AuthServiceDep, CurrentUserDep
from app.models.user import User
from app.schemas.user import (
    PasswordReset,
    UserCreate,
    UserPage,
    UserResponse,
    UserStatusUpdate,
)
from app.services.audit import AuditAction, AuditTargetType

router = APIRouter(prefix="/administrators", tags=["administrators"])


@router.get("", response_model=UserPage)
async def list_administrators(
    auth: AuthServiceDep,
    _: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UserPage:
    users, total = await auth.users.list_page(page, page_size)
    return UserPage(
        items=[UserResponse.model_validate(user) for user in users],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_administrator(
    data: UserCreate,
    auth: AuthServiceDep,
    audit: AuthenticatedAuditDep,
) -> User:
    async with audit.capture(
        action=AuditAction.ADMINISTRATOR_CREATE,
        target_type=AuditTargetType.ADMINISTRATOR,
        target_id=data.username.casefold(),
        target_label=data.username,
    ) as tracked:
        created = await auth.users.create(data, tracked)
    return created


@router.patch("/{administrator_id}/status", response_model=UserResponse)
async def set_administrator_status(
    administrator_id: str,
    data: UserStatusUpdate,
    auth: AuthServiceDep,
    audit: AuthenticatedAuditDep,
) -> User:
    async with audit.capture(
        action=(
            AuditAction.ADMINISTRATOR_ENABLE
            if data.is_active
            else AuditAction.ADMINISTRATOR_DISABLE
        ),
        target_type=AuditTargetType.ADMINISTRATOR,
        target_id=administrator_id,
        target_label=None,
    ) as tracked:
        updated = await auth.users.set_active(
            administrator_id,
            data.is_active,
            audit.actor_id,
            tracked,
        )
    return updated


@router.post(
    "/{administrator_id}/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_administrator_password(
    administrator_id: str,
    data: PasswordReset,
    auth: AuthServiceDep,
    audit: AuthenticatedAuditDep,
) -> Response:
    async with audit.capture(
        action=AuditAction.ADMINISTRATOR_PASSWORD_RESET,
        target_type=AuditTargetType.ADMINISTRATOR,
        target_id=administrator_id,
        target_label=None,
    ) as tracked:
        await auth.users.reset_password(administrator_id, data.password, tracked)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
