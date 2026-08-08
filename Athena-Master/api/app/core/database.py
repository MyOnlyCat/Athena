from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings
from app.core.postgres import postgres_server_settings


class Base(DeclarativeBase):
    pass


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        connect_args={
            "server_settings": postgres_server_settings(
                schema=settings.database_schema,
                statement_timeout_ms=settings.database_statement_timeout_ms,
                idle_transaction_timeout_ms=(
                    settings.database_idle_transaction_timeout_ms
                ),
                lock_timeout_ms=settings.database_lock_timeout_ms,
            )
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
