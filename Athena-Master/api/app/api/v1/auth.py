from fastapi import APIRouter, Request, Response, status

from app.api.deps import AuditServiceDep, AuthContextDep, AuthServiceDep, CurrentUserDep
from app.core.errors import AppError
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse
from app.schemas.user import UserResponse
from app.services.audit import AuditAction, AuditTargetType

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    auth: AuthServiceDep,
    audit: AuditServiceDep,
    request: Request,
) -> LoginResponse:
    source_ip = request.client.host if request.client else "unknown"
    throttle = request.app.state.login_throttle
    normalized_username = data.username.strip().casefold()
    async with audit.capture(
        action=AuditAction.AUTH_LOGIN,
        target_type=AuditTargetType.ADMINISTRATOR,
        target_id=normalized_username,
        target_label=data.username.strip(),
        source_ip=source_ip,
    ) as tracked:
        throttle.ensure_allowed(data.username, source_ip)
        try:
            user = await auth.authenticate(data.username, data.password, tracked)
        except AppError as exc:
            if exc.code == "INVALID_CREDENTIALS":
                throttle.record_failure(data.username, source_ip)
            raise
        throttle.reset(data.username, source_ip)
        response = LoginResponse(
            access_token=auth.issue_access_token(user),
            user=UserResponse.model_validate(user),
        )
    return response


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUserDep) -> User:
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(context: AuthContextDep, auth: AuthServiceDep) -> Response:
    await auth.revoke(context[1])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
