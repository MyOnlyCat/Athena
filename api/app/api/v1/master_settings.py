from fastapi import APIRouter, Request

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.master_setting import (
    MasterConnectionTestResponse,
    MasterSettingInput,
    MasterSettingResponse,
)
from app.services.crypto import CredentialCipher
from app.services.master_settings import MasterConfig, MasterSettingsService

router = APIRouter(prefix="/master-settings", tags=["master-settings"])


def service(request: Request, session: SessionDep) -> MasterSettingsService:
    return MasterSettingsService(
        session,
        request.app.state.settings,
        CredentialCipher(request.app.state.settings.credential_key),
    )


def response(config: MasterConfig, runtime_status: str) -> MasterSettingResponse:
    return MasterSettingResponse(
        scheme=config.scheme,
        host=config.host,
        port=config.port,
        has_token=bool(config.token),
        runtime_status=runtime_status,
    )


@router.get("", response_model=MasterSettingResponse)
async def get_master_settings(
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> MasterSettingResponse:
    runtime = request.app.state.master_runtime
    async with runtime.reconfigure():
        config = await service(request, session).get_effective()
        return response(config, runtime.status)


@router.post("/test", response_model=MasterConnectionTestResponse)
async def test_master_settings(
    data: MasterSettingInput,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> MasterConnectionTestResponse:
    runtime = request.app.state.master_runtime
    async with runtime.reconfigure():
        config = await service(request, session).resolve(data)
        await runtime.test(config)
        return MasterConnectionTestResponse()


@router.put("", response_model=MasterSettingResponse)
async def update_master_settings(
    data: MasterSettingInput,
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> MasterSettingResponse:
    runtime = request.app.state.master_runtime
    settings_service = service(request, session)
    async with runtime.reconfigure():
        config = await settings_service.resolve(data)
        await runtime.test(config)
        candidate = await runtime.prepare(config)
        try:
            await settings_service.save(data, config)
            await session.commit()
        except BaseException:
            await session.rollback()
            await runtime.discard(candidate)
            raise
        await runtime.activate(candidate)
        return response(config, runtime.status)
