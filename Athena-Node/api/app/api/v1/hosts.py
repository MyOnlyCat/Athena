from fastapi import APIRouter, Request, Response, status

from app.api.deps import CurrentUserDep, SessionDep
from app.models.host import Host
from app.schemas.host import (
    FingerprintTrust,
    HostCreate,
    HostProbeSettingInput,
    HostProbeSettingResponse,
    HostResponse,
    HostUpdate,
    SSHTestResponse,
)
from app.services.crypto import CredentialCipher
from app.services.host_probe import HostProbeSettingsService
from app.services.hosts import HostService

router = APIRouter(prefix="/hosts", tags=["hosts"])


def service(request: Request, session: SessionDep) -> HostService:
    return HostService(
        session,
        CredentialCipher(request.app.state.settings.credential_key),
        request.app.state.ssh_client,
    )


@router.get("", response_model=list[HostResponse])
async def list_hosts(request: Request, session: SessionDep, _: CurrentUserDep) -> list[Host]:
    return await service(request, session).list()


@router.get("/probe-settings", response_model=HostProbeSettingResponse)
async def get_probe_settings(
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> object:
    return await HostProbeSettingsService(
        session,
        request.app.state.settings.host_probe_interval_minutes,
    ).get()


@router.put("/probe-settings", response_model=HostProbeSettingResponse)
async def update_probe_settings(
    data: HostProbeSettingInput,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> object:
    setting = await HostProbeSettingsService(
        session,
        request.app.state.settings.host_probe_interval_minutes,
    ).update(data.interval_minutes)
    request.app.state.host_probe_scheduler.reschedule()
    return setting


@router.post("", response_model=HostResponse, status_code=status.HTTP_201_CREATED)
async def create_host(
    data: HostCreate,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Host:
    host = await service(request, session).create(data)
    request.app.state.inventory_sync.notify_change()
    return host


@router.get("/{host_id}", response_model=HostResponse)
async def get_host(
    host_id: str,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Host:
    return await service(request, session).get(host_id)


@router.put("/{host_id}", response_model=HostResponse)
async def update_host(
    host_id: str,
    data: HostUpdate,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Host:
    host = await service(request, session).update(host_id, data)
    request.app.state.inventory_sync.notify_change()
    return host


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host(
    host_id: str,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Response:
    await service(request, session).delete(host_id)
    request.app.state.inventory_sync.notify_change()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{host_id}/test", response_model=SSHTestResponse)
async def test_host(
    host_id: str,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> dict[str, object]:
    return await service(request, session).test_connection(host_id)


@router.post("/{host_id}/trust-fingerprint", response_model=HostResponse)
async def trust_fingerprint(
    host_id: str,
    data: FingerprintTrust,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> Host:
    host = await service(request, session).trust_fingerprint(host_id, data.fingerprint)
    request.app.state.inventory_sync.notify_change()
    return host
