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
        previous_config = await settings_service.get_effective()
        config = await settings_service.resolve(data)
        await runtime.test(config)
        candidate = await runtime.prepare(config)
        activated = False
        try:
            await settings_service.save(data, config)
            await runtime.activate(candidate)
            activated = True
            await session.commit()
        except BaseException as exc:
            await session.rollback()
            if activated:
                try:
                    rollback_candidate = await runtime.prepare(previous_config)
                    await runtime.activate(rollback_candidate)
                except BaseException as rollback_error:
                    exc.add_note(f"runtime rollback failed: {rollback_error!r}")
            else:
                await runtime.discard(candidate)
            raise
        return response(config, runtime.status)
