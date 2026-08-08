import asyncio
from asyncio import Lock
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException

from app.api.v1.administrators import router as administrators_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.nodes import admin_router as nodes_admin_router
from app.api.v1.nodes import node_router as nodes_node_router
from app.api.v1.overview import router as overview_router
from app.api.v1.registration_applications import (
    admin_router as registration_admin_router,
)
from app.api.v1.registration_applications import (
    node_router as registration_node_router,
)
from app.core.config import Settings, get_settings
from app.core.database import create_engine, create_session_factory
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    temporary_unavailable_handler,
    validation_error_handler,
)
from app.core.migrations import require_database_at_head
from app.services.auth import AuthService, LoginThrottle
from app.services.heartbeats import NodeRequestThrottle
from app.services.registrations import (
    RegistrationService,
    RegistrationThrottle,
    registration_maintenance_loop,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(active_settings)
        maintenance_task: asyncio.Task[None] | None = None
        app.state.db_engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            await require_database_at_head(engine)

            if active_settings.bootstrap_username and active_settings.bootstrap_password:
                async with app.state.session_factory() as session:
                    auth = AuthService(session, active_settings, administrator_write_lock)
                    existing = await auth.users.get_by_normalized_username(
                        active_settings.bootstrap_username
                    )
                    if existing is None:
                        await auth.users.create_bootstrap_admin(
                            active_settings.bootstrap_username,
                            active_settings.bootstrap_password,
                        )
            async with registration_write_lock:
                async with app.state.session_factory() as session:
                    registrations = RegistrationService(
                        session,
                        active_settings.credential_key,
                    )
                    await registrations.backfill_token_fingerprints()
                    await registrations.maintain(datetime.now(UTC))
            maintenance_task = asyncio.create_task(
                registration_maintenance_loop(
                    app.state.session_factory,
                    active_settings.credential_key,
                    registration_write_lock,
                ),
                name="registration-maintenance",
            )
            yield
        finally:
            if maintenance_task is not None:
                maintenance_task.cancel()
                try:
                    await maintenance_task
                except asyncio.CancelledError:
                    pass
            await engine.dispose()

    app = FastAPI(
        title="Athena Master API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = active_settings
    app.state.login_throttle = LoginThrottle()
    administrator_write_lock = Lock()
    app.state.administrator_write_lock = administrator_write_lock
    registration_write_lock = Lock()
    app.state.registration_write_lock = registration_write_lock
    app.state.registration_throttle = RegistrationThrottle()
    app.state.node_write_lock = Lock()
    app.state.node_request_throttle = NodeRequestThrottle()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        OperationalError,
        temporary_unavailable_handler,
    )
    app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        validation_error_handler,  # type: ignore[arg-type]
    )
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(administrators_router, prefix="/api/v1")
    app.include_router(registration_admin_router, prefix="/api/v1")
    app.include_router(registration_node_router, prefix="/api/node/v1")
    app.include_router(nodes_admin_router, prefix="/api/v1")
    app.include_router(nodes_node_router, prefix="/api/node/v1")
    app.include_router(overview_router, prefix="/api/v1")

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        async with app.state.session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "service": active_settings.service_name,
            "database": "ok",
        }

    return app
