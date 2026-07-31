import asyncio
import socket
from collections.abc import Coroutine
from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import CurrentUserDep, SessionDep
from app.core.errors import AppError
from app.schemas.master_setting import (
    MasterConnectionTestResponse,
    MasterRuntimeStatus,
    MasterSettingInput,
    MasterSettingResponse,
    RegistrationApplicationResponse,
    RegistrationStatusResponse,
)
from app.services.crypto import CredentialCipher
from app.services.master_client import MasterClient
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
    registration_status: str,
) -> MasterSettingResponse:
    return MasterSettingResponse(
        node_id=node_id,
        node_name=node_name,
        scheme=config.scheme,
        host=config.host,
        port=config.port,
        has_token=bool(config.token),
        runtime_status=runtime_status,
        registration_status=registration_status,
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
        row = await service(request, session).get_row()
        identity = request.app.state.node_identity
        return response(
            config,
            runtime.status,
            node_id=identity.node_id,
            node_name=identity.reported_name,
            registration_status=(
                row.registration_status if row is not None else "not_submitted"
            ),
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
        row = await settings_service.get_row()
        return response(
            config,
            runtime.status,
            node_id=identity.node_id,
            node_name=identity.reported_name,
            registration_status=(
                row.registration_status if row is not None else "not_submitted"
            ),
        )


@router.post(
    "/registration",
    response_model=RegistrationApplicationResponse,
    status_code=202,
)
async def submit_registration_application(
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> RegistrationApplicationResponse:
    settings_service = service(request, session)
    config = await settings_service.get_effective()
    if not config.host or not config.token:
        raise AppError(
            "MASTER_SETTINGS_REQUIRED",
            "请先保存主节点地址和 Token",
        )
    identity = request.app.state.node_identity
    client = MasterClient(
        config.base_url,
        identity.node_id,
        config.token,
    )
    try:
        result = await client.submit_registration(
            {
                "node_id": identity.node_id,
                "reported_name": identity.reported_name,
                "hostname": socket.gethostname(),
                "software_version": request.app.state.settings.node_version,
            }
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            "REGISTRATION_SUBMISSION_FAILED",
            "注册申请提交失败，请检查主节点连接",
        ) from exc
    finally:
        await client.close()
    if result.get("status") != "pending":
        raise AppError(
            "REGISTRATION_RESPONSE_INVALID",
            "主节点返回了无法识别的注册状态",
        )
    await settings_service.set_registration_pending()
    return RegistrationApplicationResponse(status="pending")


@router.post(
    "/registration/status",
    response_model=RegistrationStatusResponse,
)
async def synchronize_registration_status(
    request: Request,
    session: SessionDep,
    _: CurrentUserDep,
) -> RegistrationStatusResponse:
    settings_service = service(request, session)
    row = await settings_service.get_row()
    if row is None or row.registration_status != "pending":
        return RegistrationStatusResponse(
            status="approved"
            if row is not None and row.registration_status == "approved"
            else "pending"
        )
    config = await settings_service.get_effective()
    identity = request.app.state.node_identity
    client = MasterClient(
        config.base_url,
        identity.node_id,
        config.token,
    )
    try:
        async with asyncio.timeout(3):
            result = await client.get_registration_status()
    except Exception:
        return RegistrationStatusResponse(status="pending")
    finally:
        await client.close()
    if result.get("status") == "approved":
        await settings_service.set_registration_status("approved")
        return RegistrationStatusResponse(status="approved")
    return RegistrationStatusResponse(status="pending")
