import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.files import router as files_router
from app.api.v1.hosts import router as hosts_router
from app.api.v1.master_settings import router as master_settings_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.terminal import router as terminal_router
from app.api.v1.users import router as users_router
from app.core.config import Settings, get_settings
from app.core.database import Base, create_engine, create_session_factory
from app.core.errors import AppError, app_error_handler, http_error_handler
from app.core.logging import configure_logging
from app.models.audit import AuditLog
from app.schemas.user import UserCreate
from app.services.artifacts import ArtifactService
from app.services.auth import AuthService, LoginThrottle
from app.services.crypto import CredentialCipher
from app.services.deployment_gateway import AsyncDeploymentGateway
from app.services.files import AsyncRemoteFiles
from app.services.host_probe import HostProbeScheduler, HostProbeSettingsService
from app.services.inventory_sync import InventorySynchronizer
from app.services.master_runtime import MasterRuntime
from app.services.master_settings import MasterSettingsService
from app.services.node_identity import NodeIdentityService
from app.services.ssh import AsyncSSHClient
from app.services.terminal import AsyncTerminalGateway, TerminalTicketStore


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(active_settings)
        artifact_http: httpx.AsyncClient | None = None
        master_runtime: MasterRuntime | None = None
        host_probe_scheduler: HostProbeScheduler | None = None
        try:
            app.state.db_engine = engine
            app.state.session_factory = create_session_factory(engine)
            artifact_http = httpx.AsyncClient(timeout=None)

            def publish_runtime(inventory: Any | None, executor: Any | None) -> None:
                app.state.inventory_sync = inventory or InventorySynchronizer(
                    runtime_settings,
                    app.state.session_factory,
                )
                app.state.deployment_executor = executor

            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with app.state.session_factory() as session:
                identity = await NodeIdentityService(session, active_settings).get_or_create()
            runtime_settings = active_settings.model_copy(
                update={
                    "node_id": identity.node_id,
                    "node_name": identity.reported_name,
                }
            )
            app.state.node_identity = identity
            app.state.settings = runtime_settings
            master_runtime = MasterRuntime(
                settings=runtime_settings,
                session_factory=app.state.session_factory,
                artifact_service=ArtifactService(
                    artifact_http,
                    runtime_settings.data_dir / "artifacts",
                    allow_http=runtime_settings.allow_http_artifacts,
                ),
                gateway=AsyncDeploymentGateway(),
                cipher=CredentialCipher(runtime_settings.credential_key),
                start_worker=runtime_settings.environment != "test",
                on_change=publish_runtime,
            )
            app.state.master_runtime = master_runtime
            async with app.state.session_factory() as session:
                await HostProbeSettingsService(
                    session,
                    active_settings.host_probe_interval_minutes,
                ).get()
            if active_settings.bootstrap_username and active_settings.bootstrap_password:
                async with app.state.session_factory() as session:
                    auth = AuthService(session, active_settings)
                    existing = await auth.users.get_by_normalized_username(
                        active_settings.bootstrap_username
                    )
                    if existing is None:
                        await auth.users.create(
                            UserCreate(
                                username=active_settings.bootstrap_username,
                                password=active_settings.bootstrap_password,
                            )
                        )
            async with app.state.session_factory() as session:
                config = await MasterSettingsService(
                    session,
                    runtime_settings,
                    CredentialCipher(runtime_settings.credential_key),
                ).get_effective()
            await master_runtime.apply(config, recover=True)
            host_probe_scheduler = HostProbeScheduler(
                app.state.session_factory,
                CredentialCipher(active_settings.credential_key),
                app.state.ssh_client,
                default_interval_minutes=active_settings.host_probe_interval_minutes,
            )
            app.state.host_probe_scheduler = host_probe_scheduler
            if active_settings.environment != "test":
                host_probe_scheduler.start()
            yield
        finally:
            active_error = sys.exception()
            cleanup_errors: list[BaseException] = []
            if host_probe_scheduler is not None:
                try:
                    await host_probe_scheduler.stop()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if master_runtime is not None:
                try:
                    await master_runtime.stop()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if artifact_http is not None:
                try:
                    await artifact_http.aclose()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                await engine.dispose()
            except BaseException as exc:
                cleanup_errors.append(exc)

            if active_error is not None:
                for error in cleanup_errors:
                    active_error.add_note(f"lifespan cleanup failed: {error!r}")
            elif len(cleanup_errors) == 1:
                raise cleanup_errors[0]
            elif cleanup_errors:
                raise BaseExceptionGroup("lifespan cleanup failed", cleanup_errors)

    app = FastAPI(
        title="Athena Node API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.login_throttle = LoginThrottle()
    app.state.ssh_client = AsyncSSHClient()
    app.state.terminal_tickets = TerminalTicketStore()
    app.state.terminal_gateway = AsyncTerminalGateway()
    app.state.remote_files = AsyncRemoteFiles()
    app.state.inventory_sync = InventorySynchronizer(active_settings, None)
    app.state.host_probe_scheduler = None
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(files_router, prefix="/api/v1")
    app.include_router(hosts_router, prefix="/api/v1")
    app.include_router(master_settings_router, prefix="/api/v1")
    app.include_router(terminal_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.middleware("http")
    async def audit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        user_id = getattr(request.state, "user_id", None)
        if user_id and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            async with request.app.state.session_factory() as session:
                session.add(
                    AuditLog(
                        user_id=user_id,
                        action=f"{request.method} {request.url.path}",
                        resource_type="http",
                        result="success" if response.status_code < 400 else "failure",
                        source_ip=request.client.host if request.client else None,
                        details={
                            "status_code": response.status_code,
                            "request_id": request.state.request_id,
                        },
                    )
                )
                await session.commit()
        return response

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": active_settings.service_name}

    return app
