from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, status

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.registration import (
    AccessNodeResponse,
    RegistrationApplicationPage,
    RegistrationApplicationResponse,
    RegistrationApproval,
    RegistrationRejection,
    RegistrationStatusResponse,
    RegistrationSubmitted,
)
from app.services.registrations import RegistrationService

node_router = APIRouter(tags=["node-registration"])
admin_router = APIRouter(
    prefix="/registration-applications",
    tags=["registration-applications"],
)


def service(request: Request, session: SessionDep) -> RegistrationService:
    return RegistrationService(
        session,
        request.app.state.settings.credential_key,
        request.app.state.registration_throttle,
    )


@node_router.post(
    "/registration-applications",
    response_model=RegistrationSubmitted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_registration_application(
    request: Request,
    session: SessionDep,
    node_id: Annotated[str, Header(alias="X-Node-Id")],
    timestamp_value: Annotated[str, Header(alias="X-Timestamp")],
    nonce: Annotated[str, Header(alias="X-Nonce")],
    signature: Annotated[str, Header(alias="X-Signature")],
) -> RegistrationSubmitted:
    body = await request.body()
    async with request.app.state.registration_write_lock:
        await service(request, session).submit(
            body=body,
            node_id=node_id,
            timestamp=timestamp_value,
            nonce=nonce,
            signature=signature,
            source_ip=request.client.host if request.client else None,
            received_at=datetime.now(UTC),
        )
    return RegistrationSubmitted(status="pending")


@node_router.post(
    "/registration-applications/status",
    response_model=RegistrationStatusResponse,
)
async def get_registration_status(
    request: Request,
    session: SessionDep,
    node_id: Annotated[str, Header(alias="X-Node-Id")],
    timestamp_value: Annotated[str, Header(alias="X-Timestamp")],
    nonce: Annotated[str, Header(alias="X-Nonce")],
    signature: Annotated[str, Header(alias="X-Signature")],
) -> RegistrationStatusResponse:
    body = await request.body()
    registration_status = await service(request, session).status(
        body=body,
        node_id=node_id,
        timestamp=timestamp_value,
        nonce=nonce,
        signature=signature,
        received_at=datetime.now(UTC),
    )
    return RegistrationStatusResponse(status=registration_status)


@admin_router.get(
    "",
    response_model=RegistrationApplicationPage,
    response_model_exclude_none=True,
)
async def list_registration_applications(
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RegistrationApplicationPage:
    applications, total = await service(request, session).list_page(page, page_size)
    return RegistrationApplicationPage(
        items=[
            RegistrationApplicationResponse.model_validate(application).model_copy(
                update={"identity_verified": application.status == "approved"}
            )
            for application in applications
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@admin_router.post("/{application_id}/approve", response_model=AccessNodeResponse)
async def approve_registration_application(
    application_id: str,
    data: RegistrationApproval,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> AccessNodeResponse:
    async with request.app.state.registration_write_lock:
        node = await service(request, session).approve(application_id, data.token)
    return AccessNodeResponse.model_validate(node)


@admin_router.post(
    "/{application_id}/reject",
    response_model=RegistrationApplicationResponse,
    response_model_exclude_none=True,
)
async def reject_registration_application(
    application_id: str,
    data: RegistrationRejection,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> RegistrationApplicationResponse:
    async with request.app.state.registration_write_lock:
        application = await service(request, session).reject(application_id, data.reason)
    return RegistrationApplicationResponse.model_validate(application)


@admin_router.post(
    "/{application_id}/restore",
    response_model=RegistrationApplicationResponse,
    response_model_exclude_none=True,
)
async def restore_registration_application(
    application_id: str,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> RegistrationApplicationResponse:
    async with request.app.state.registration_write_lock:
        application = await service(request, session).restore(application_id)
    return RegistrationApplicationResponse.model_validate(application)
