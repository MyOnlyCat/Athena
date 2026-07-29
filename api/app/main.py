import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.api.v1.auth import router as auth_router
from app.api.v1.files import router as files_router
from app.api.v1.hosts import router as hosts_router
from app.api.v1.terminal import router as terminal_router
from app.api.v1.users import router as users_router
from app.core.config import Settings, get_settings
from app.core.database import Base, create_engine, create_session_factory
from app.core.errors import AppError, app_error_handler, http_error_handler
from app.core.logging import configure_logging
from app.schemas.user import UserCreate
from app.services.auth import AuthService, LoginThrottle
from app.services.files import AsyncRemoteFiles
from app.services.inventory_sync import InventorySynchronizer
from app.services.master_client import MasterClient
from app.services.ssh import AsyncSSHClient
from app.services.terminal import AsyncTerminalGateway, TerminalTicketStore


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(active_settings)
        app.state.db_engine = engine
        app.state.session_factory = create_session_factory(engine)
        master_client = None
        if active_settings.master_node_url and active_settings.node_token:
            master_client = MasterClient(
                active_settings.master_node_url,
                active_settings.node_id,
                active_settings.node_token,
            )
        app.state.inventory_sync = InventorySynchronizer(
            active_settings,
            app.state.session_factory,
            master_client,
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
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
        stop = asyncio.Event()
        worker = None
        if master_client is not None and active_settings.environment != "test":
            worker = asyncio.create_task(app.state.inventory_sync.run(stop))
        yield
        stop.set()
        app.state.inventory_sync.notify_change()
        if worker is not None:
            await worker
        if master_client is not None:
            await master_client.close()
        await engine.dispose()

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
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(files_router, prefix="/api/v1")
    app.include_router(hosts_router, prefix="/api/v1")
    app.include_router(terminal_router, prefix="/api/v1")
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

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": active_settings.service_name}

    return app
