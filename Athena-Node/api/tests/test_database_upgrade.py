import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine

from app import models as _models  # noqa: F401
from app.core.database import Base

API_ROOT = Path(__file__).resolve().parents[1]


def run_upgrade(database: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "app.core.database_upgrade",
            "--database-url",
            f"sqlite+aiosqlite:///{database.as_posix()}",
        ],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_unversioned_create_all_database_is_safely_baselined_and_upgraded(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE master_settings DROP COLUMN registration_status"
        )
        connection.exec_driver_sql("ALTER TABLE hosts DROP COLUMN last_test_code")
    engine.dispose()

    upgraded = run_upgrade(database)

    assert upgraded.returncode == 0, upgraded.stderr
    assert Path(f"{database}.pre-alembic-0007_node_identity.bak").exists()
    with sqlite3.connect(database) as connection:
        master_columns = {
            row[1]
            for row in connection.execute('PRAGMA table_info("master_settings")')
        }
        host_columns = {
            row[1]
            for row in connection.execute('PRAGMA table_info("hosts")')
        }
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    assert "registration_status" in master_columns
    assert "last_test_code" in host_columns
    assert version == ("0009_host_test_code",)


def test_unknown_unversioned_schema_is_rejected_without_stamping(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unknown.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")

    rejected = run_upgrade(database)

    assert rejected.returncode != 0
    assert "无法安全识别旧数据库结构" in rejected.stderr
    with sqlite3.connect(database) as connection:
        version_table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'alembic_version'"
        ).fetchone()
    assert version_table is None
