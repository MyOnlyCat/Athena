from asyncio import Lock
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from starlette.exceptions import HTTPException

from app.api.v1.administrators import router as administrators_router
from app.api.v1.auth import router as auth_router
from app.core.config import Settings, get_settings
from app.core.database import Base, create_engine, create_session_factory
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    validation_error_handler,
)
from app.services.auth import AuthService, LoginThrottle


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(active_settings)
        app.state.db_engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            if active_settings.environment == "test":
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)

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
            yield
        finally:
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
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        validation_error_handler,  # type: ignore[arg-type]
    )
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(administrators_router, prefix="/api/v1")

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
