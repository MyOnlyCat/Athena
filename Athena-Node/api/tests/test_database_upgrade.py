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
        connection.exec_driver_sql(
            "INSERT INTO hosts "
            "(id,name,address,port,username,encrypted_password,tags,is_local,"
            "last_test_status,last_test_message,last_tested_at,created_at,updated_at) "
            "VALUES "
            "('host-success','success-host','10.0.0.1',22,'root','encrypted','[]',0,"
            "'success','SSH 连接成功','2026-07-31 08:00:00',"
            "'2026-07-31 08:00:00','2026-07-31 08:00:00'),"
            "('host-timeout','timeout-host','10.0.0.2',22,'root','encrypted','[]',0,"
            "'failed','SSH 连接超时','2026-07-31 08:00:00',"
            "'2026-07-31 08:00:00','2026-07-31 08:00:00')"
        )
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
        test_results = connection.execute(
            "SELECT name, last_test_code FROM hosts ORDER BY name"
        ).fetchall()
    assert "registration_status" in master_columns
    assert "last_test_code" in host_columns
    assert version == ("0009_host_test_code",)
    assert test_results == [
        ("success-host", "SSH_CONNECTED"),
        ("timeout-host", "SSH_TIMEOUT"),
    ]


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
