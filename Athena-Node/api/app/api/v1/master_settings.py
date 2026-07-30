import asyncio
from collections.abc import Coroutine
from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.master_setting import (
    MasterConnectionTestResponse,
    MasterRuntimeStatus,
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


def response(
    config: MasterConfig,
    runtime_status: MasterRuntimeStatus,
    *,
    node_id: str,
    node_name: str,
) -> MasterSettingResponse:
    return MasterSettingResponse(
        node_id=node_id,
        node_name=node_name,
        scheme=config.scheme,
        host=config.host,
        port=config.port,
        has_token=bool(config.token),
        runtime_status=runtime_status,
    )


async def _finish_owned(
    operation: Coroutine[Any, Any, None],
    *,
    name: str,
) -> asyncio.CancelledError | None:
    task = asyncio.create_task(operation, name=name)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = exc
    task.result()
    return cancellation


async def _commit_and_activate(
    session: SessionDep,
    runtime: Any,
    candidate: Any,
) -> None:
    await session.commit()
    await runtime.activate(candidate)


@router.get("", response_model=MasterSettingResponse)
async def get_master_settings(
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> MasterSettingResponse:
    runtime = request.app.state.master_runtime
    async with runtime.reconfigure():
        config = await service(request, session).get_effective()
        identity = request.app.state.node_identity
        return response(
            config,
            runtime.status,
            node_id=identity.node_id,
            node_name=identity.reported_name,
        )


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
        cancellation: asyncio.CancelledError | None = None
        try:
            await settings_service.save(data, config)
            cancellation = await _finish_owned(
                _commit_and_activate(session, runtime, candidate),
                name="master-settings-commit-and-activate",
            )
        except BaseException as exc:
            try:
                await session.rollback()
            except BaseException as rollback_error:
                exc.add_note(f"settings rollback failed: {rollback_error!r}")
            finally:
                try:
                    await runtime.discard(candidate)
                except BaseException as discard_error:
                    exc.add_note(f"candidate discard failed: {discard_error!r}")
            raise
        if cancellation is not None:
            raise cancellation
        identity = request.app.state.node_identity
        return response(
            config,
            runtime.status,
            node_id=identity.node_id,
            node_name=identity.reported_name,
        )
