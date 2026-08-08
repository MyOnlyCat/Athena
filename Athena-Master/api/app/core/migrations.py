from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseSchemaError(RuntimeError):
    """Raised when the runtime database is not at the required Alembic head."""


def expected_database_heads() -> frozenset[str]:
    api_root = Path(__file__).resolve().parents[2]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


async def require_database_at_head(engine: AsyncEngine) -> None:
    expected_heads = expected_database_heads()
    if len(expected_heads) != 1:
        raise DatabaseSchemaError("Alembic 必须且只能存在一个 head")

    async with engine.connect() as connection:
        version_table = await connection.scalar(
            text("SELECT to_regclass(current_schema() || '.alembic_version')")
        )
        if version_table is None:
            raise DatabaseSchemaError(
                "数据库尚未迁移到 Alembic head；请先执行 alembic upgrade head"
            )
        current_heads = frozenset(
            str(version)
            for version in (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalars()
        )

    if current_heads != expected_heads:
        raise DatabaseSchemaError(
            "数据库不在 Alembic head；请先执行 alembic upgrade head"
        )
