import argparse
import os
import sqlite3
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from alembic import command
from app import models as _models  # noqa: F401
from app.core.database import Base

LEGACY_BASELINE_REVISION = "0007_node_identity"
API_ROOT = Path(__file__).resolve().parents[2]


def _sqlite_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        return None
    database = Path(url.database)
    return database if database.is_absolute() else (API_ROOT / database).resolve()


def _read_schema(database: Path) -> dict[str, set[str]]:
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        return {
            table: {
                row[1]
                for row in connection.execute(
                    f'PRAGMA table_info("{table.replace('"', '""')}")'
                )
            }
            for table in tables
        }


def _matches_legacy_0007(database_url: str) -> bool:
    url = make_url(database_url).set(drivername="sqlite")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            differences = compare_metadata(
                MigrationContext.configure(connection),
                Base.metadata,
            )
    finally:
        engine.dispose()
    additions = {
        (difference[2], difference[3].name)
        for difference in differences
        if isinstance(difference, tuple)
        and len(difference) == 4
        and difference[0] == "add_column"
    }
    return len(additions) == len(differences) and additions == {
        ("master_settings", "registration_status"),
        ("hosts", "last_test_code"),
    }


def _backup_legacy_database(database: Path) -> Path:
    backup = Path(f"{database}.pre-alembic-{LEGACY_BASELINE_REVISION}.bak")
    if backup.exists():
        return backup
    with (
        sqlite3.connect(database) as source,
        sqlite3.connect(backup) as destination,
    ):
        source.backup(destination)
    return backup


def upgrade_database(database_url: str) -> None:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    os.environ["ATHENA_DATABASE_URL"] = database_url
    database = _sqlite_path(database_url)

    if database is not None and database.exists():
        schema = _read_schema(database)
        if schema and "alembic_version" not in schema:
            if not _matches_legacy_0007(database_url):
                raise RuntimeError(
                    "无法安全识别旧数据库结构；未写入 Alembic 基线。"
                    "请备份数据库并人工检查迁移状态。"
                )
            backup = _backup_legacy_database(database)
            print(f"已备份旧数据库：{backup}")
            command.stamp(config, LEGACY_BASELINE_REVISION)

    command.upgrade(config, "head")


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely upgrade the Athena Node database.")
    parser.add_argument("--database-url", required=True)
    arguments = parser.parse_args()
    try:
        upgrade_database(arguments.database_url)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
