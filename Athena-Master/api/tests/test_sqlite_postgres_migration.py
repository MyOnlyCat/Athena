from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, insert, text

from app.cli.migrate_sqlite_to_postgres import main as migrate_cli_main
from app.cli.sqlite_postgres import (
    ImportVerificationError,
    SourceValidationError,
    TargetConflictError,
    TargetDatabaseError,
    TargetValidationError,
    inspect_sqlite_source,
    migrate_sqlite_to_postgres,
    verify_postgres_import,
)
from app.cli.verify_postgres_import import main as verify_cli_main
from app.core.database import Base
from app.models import (
    AccessNode,
    AuditLog,
    HostAsset,
    NodeNonce,
    RegistrationApplication,
    RevokedToken,
    User,
)

if TYPE_CHECKING:
    from tests.postgres import PostgresTestSchema


CREDENTIAL_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
NODE_TOKEN = "node-token-for-offline-migration"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rewrite_sqlite_table_definition(
    path: Path,
    *,
    table_name: str,
    old: str,
    new: str,
) -> None:
    connection = sqlite3.connect(path)
    try:
        current = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        assert current is not None
        current_sql = str(current[0])
        assert old in current_sql
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?",
            (current_sql.replace(old, new, 1), table_name),
        )
        schema_version = int(
            connection.execute("PRAGMA schema_version").fetchone()[0]
        )
        connection.execute(f"PRAGMA schema_version = {schema_version + 1}")
        connection.execute("PRAGMA writable_schema = OFF")
        connection.commit()
    finally:
        connection.close()


def _create_source_database(path: Path) -> tuple[str, str]:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    encrypted_token = Fernet(CREDENTIAL_KEY.encode()).encrypt(NODE_TOKEN.encode()).decode()
    token_fingerprint = hmac.new(
        CREDENTIAL_KEY.encode(),
        NODE_TOKEN.encode(),
        hashlib.sha256,
    ).hexdigest()
    now = datetime(2026, 8, 8, 1, 2, 3, 456789, tzinfo=UTC)

    with engine.begin() as connection:
        connection.execute(
            insert(User),
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "username": "管理员",
                "normalized_username": "管理员",
                "password_hash": "$argon2id$fixture",
                "is_active": True,
                "auth_version": 2,
                "last_login_at": now,
                "created_at": now - timedelta(days=2),
                "updated_at": now - timedelta(days=1),
            },
        )
        connection.execute(
            insert(RevokedToken),
            {
                "jti": "00000000-0000-0000-0000-000000000002",
                "expires_at": now + timedelta(hours=1),
            },
        )
        connection.execute(
            insert(RegistrationApplication),
            {
                "id": "00000000-0000-0000-0000-000000000003",
                "node_id": "00000000-0000-0000-0000-000000000004",
                "reported_name": "上海节点",
                "hostname": "node-01",
                "software_version": "0.1.0",
                "raw_body": b'{"node_id":"fixture","name":"\xe4\xb8\x8a\xe6\xb5\xb7"}',
                "request_path": "/api/node/v1/registration-applications",
                "auth_timestamp": "1786150923",
                "auth_nonce": "0123456789abcdef0123456789abcdef",
                "auth_signature": "a" * 64,
                "source_ip": "192.0.2.10",
                "status": "approved",
                "rejection_reason": None,
                "received_at": now - timedelta(days=1),
                "status_changed_at": now,
            },
        )
        connection.execute(
            insert(AccessNode),
            {
                "node_id": "00000000-0000-0000-0000-000000000004",
                "reported_name": "上海节点",
                "hostname": "node-01",
                "software_version": "0.1.0",
                "management_status": "active",
                "display_name": "生产节点",
                "notes": None,
                "management_tags": ["生产", "华东"],
                "disable_reason": None,
                "encrypted_token": encrypted_token,
                "token_fingerprint": token_fingerprint,
                "approved_at": now,
                "last_heartbeat_at": now,
            },
        )
        connection.execute(
            insert(NodeNonce),
            {
                "node_id": "00000000-0000-0000-0000-000000000004",
                "nonce": "fedcba9876543210fedcba9876543210",
                "received_at": now,
            },
        )
        connection.execute(
            insert(HostAsset),
            {
                "node_id": "00000000-0000-0000-0000-000000000004",
                "host_id": "00000000-0000-0000-0000-000000000005",
                "name": "应用主机",
                "address": "2001:db8::10",
                "port": 22,
                "username": "deploy",
                "tags": ["api", "蓝组"],
                "is_local": False,
                "last_test_status": "success",
                "last_test_code": None,
                "last_tested_at": now,
                "retired_at": None,
            },
        )
        connection.execute(
            insert(AuditLog),
            {
                "id": "00000000-0000-0000-0000-000000000006",
                "actor_id": "00000000-0000-0000-0000-000000000001",
                "actor_username": "管理员",
                "action": "registration.approve",
                "target_type": "registration_application",
                "target_id": "00000000-0000-0000-0000-000000000003",
                "target_label": "上海节点",
                "result": "success",
                "source_ip": "192.0.2.20",
                "error_code": None,
                "created_at": now,
            },
        )
        connection.execute(
            text(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            ),
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES "
                 "('0008_operation_audit')"),
        )
    engine.dispose()
    return encrypted_token, token_fingerprint


def _create_empty_source_database(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            ),
        )
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES "
                 "('0008_operation_audit')"),
        )
    engine.dispose()


def test_inspect_sqlite_source_is_read_only_and_reports_all_phase_one_tables(
    tmp_path: Path,
) -> None:
    source = tmp_path / "master.db"
    encrypted_token, token_fingerprint = _create_source_database(source)
    before = _sha256(source)
    before_stat = source.stat()

    report = inspect_sqlite_source(source, credential_key=CREDENTIAL_KEY)

    assert report.source_sha256 == before == _sha256(source)
    assert report.source_size == before_stat.st_size == source.stat().st_size
    assert report.source_mtime_ns == before_stat.st_mtime_ns == source.stat().st_mtime_ns
    assert report.source_unchanged is True
    assert report.source_revision == "0008_operation_audit"
    assert report.table_counts == {
        "access_nodes": 1,
        "alembic_version": 1,
        "audit_logs": 1,
        "host_assets": 1,
        "node_nonces": 1,
        "registration_applications": 1,
        "revoked_tokens": 1,
        "users": 1,
    }
    serialized = report.to_json()
    assert NODE_TOKEN not in serialized
    assert encrypted_token not in serialized
    assert token_fingerprint not in serialized


@pytest.mark.asyncio
async def test_empty_postgres_import_is_verified_through_the_public_seam(
    tmp_path: Path,
    migrated_postgres_schema: PostgresTestSchema,
) -> None:
    source = tmp_path / "master.db"
    encrypted_token, _ = _create_source_database(source)
    before = _sha256(source)

    imported = await migrate_sqlite_to_postgres(
        source,
        postgres_url=migrated_postgres_schema.database_url,
        credential_key=CREDENTIAL_KEY,
        target_schema=migrated_postgres_schema.name,
        backup_dir=tmp_path / "backups",
    )
    repeated = await migrate_sqlite_to_postgres(
        source,
        postgres_url=migrated_postgres_schema.database_url,
        credential_key=CREDENTIAL_KEY,
        target_schema=migrated_postgres_schema.name,
        backup_dir=tmp_path / "repeat-backup",
    )
    verified = await verify_postgres_import(
        source,
        postgres_url=migrated_postgres_schema.database_url,
        credential_key=CREDENTIAL_KEY,
        target_schema=migrated_postgres_schema.name,
    )

    assert imported.status == "imported"
    assert repeated.status == "already_current"
    assert verified.status == "verified"
    assert imported.table_counts == repeated.table_counts == verified.table_counts
    assert imported.table_digests == repeated.table_digests == verified.table_digests
    assert imported.verification is not None
    assert repeated.verification is not None
    assert verified.verification is not None
    assert imported.verification.algorithm == "athena-offline-verification-v1"
    assert (
        imported.verification.tables
        == repeated.verification.tables
        == verified.verification.tables
    )
    assert (
        imported.verification.tables["users"].sha256
        != imported.table_digests["users"]
    )
    assert (
        imported.verification.tables["users"].sha256
        == "4adb297f997677c469223062ac7a6ff690d3c6317c10c220b3923fabe60d1b7c"
    )
    assert imported.table_counts["node_nonces"] == 1
    assert imported.table_counts["audit_logs"] == 1
    assert imported.source_sha256 == verified.source_sha256 == before
    assert _sha256(source) == before
    assert imported.backup_path is not None
    assert await asyncio.to_thread(Path(imported.backup_path).is_file)
    serialized_report = imported.to_json()
    assert migrated_postgres_schema.database_url not in serialized_report
    assert NODE_TOKEN not in serialized_report
    assert encrypted_token not in serialized_report
    engine = migrated_postgres_schema.create_engine()
    try:
        async with engine.connect() as connection:
            preserved = (
                await connection.execute(
                    text(
                        "SELECT n.node_id, n.encrypted_token, "
                        "r.raw_body, r.received_at "
                        "FROM access_nodes AS n "
                        "JOIN registration_applications AS r ON r.node_id = n.node_id"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    assert preserved["node_id"] == "00000000-0000-0000-0000-000000000004"
    assert preserved["encrypted_token"] == encrypted_token
    assert preserved["raw_body"] == b'{"node_id":"fixture","name":"\xe4\xb8\x8a\xe6\xb5\xb7"}'
    assert preserved["received_at"] == datetime(
        2026,
        8,
        7,
        1,
        2,
        3,
        456789,
        tzinfo=UTC,
    )


@pytest.mark.asyncio
async def test_partial_postgres_target_fails_closed_without_overwriting_rows(
    tmp_path: Path,
    migrated_postgres_schema: PostgresTestSchema,
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)
    engine = migrated_postgres_schema.create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id,username,normalized_username,password_hash,is_active,auth_version,"
                    "created_at,updated_at) VALUES "
                    "('partial-user','partial','partial','hash',true,0,"
                    "'2026-08-08T00:00:00Z','2026-08-08T00:00:00Z')"
                )
            )
    finally:
        await engine.dispose()

    with pytest.raises(TargetConflictError):
        await migrate_sqlite_to_postgres(
            source,
            postgres_url=migrated_postgres_schema.database_url,
            credential_key=CREDENTIAL_KEY,
            target_schema=migrated_postgres_schema.name,
            backup_dir=tmp_path / "backups",
        )

    engine = migrated_postgres_schema.create_engine()
    try:
        async with engine.connect() as connection:
            evidence = (
                await connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM users) AS users, "
                        "(SELECT min(id) FROM users) AS user_id, "
                        "(SELECT count(*) FROM access_nodes) AS nodes"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()
    assert dict(evidence) == {"users": 1, "user_id": "partial-user", "nodes": 0}


@pytest.mark.asyncio
async def test_conflicting_source_and_verifier_mismatch_preserve_the_original_import(
    tmp_path: Path,
    migrated_postgres_schema: PostgresTestSchema,
) -> None:
    original = tmp_path / "original.db"
    conflicting = tmp_path / "conflicting.db"
    _create_source_database(original)
    _create_source_database(conflicting)
    conflict_engine = create_engine(f"sqlite:///{conflicting.as_posix()}")
    with conflict_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE users SET username = 'different', "
                "normalized_username = 'different'"
            )
        )
    conflict_engine.dispose()
    await migrate_sqlite_to_postgres(
        original,
        postgres_url=migrated_postgres_schema.database_url,
        credential_key=CREDENTIAL_KEY,
        target_schema=migrated_postgres_schema.name,
        backup_dir=tmp_path / "original-backup",
    )

    with pytest.raises(TargetConflictError):
        await migrate_sqlite_to_postgres(
            conflicting,
            postgres_url=migrated_postgres_schema.database_url,
            credential_key=CREDENTIAL_KEY,
            target_schema=migrated_postgres_schema.name,
            backup_dir=tmp_path / "conflict-backup",
        )
    with pytest.raises(ImportVerificationError):
        await verify_postgres_import(
            conflicting,
            postgres_url=migrated_postgres_schema.database_url,
            credential_key=CREDENTIAL_KEY,
            target_schema=migrated_postgres_schema.name,
        )

    verified = await verify_postgres_import(
        original,
        postgres_url=migrated_postgres_schema.database_url,
        credential_key=CREDENTIAL_KEY,
        target_schema=migrated_postgres_schema.name,
    )
    assert verified.status == "verified"


@pytest.mark.asyncio
async def test_failed_mid_import_rolls_back_every_postgres_row(
    tmp_path: Path,
    migrated_postgres_schema: PostgresTestSchema,
) -> None:
    invalid = tmp_path / "invalid.db"
    empty = tmp_path / "empty.db"
    _create_source_database(invalid)
    invalid_engine = create_engine(f"sqlite:///{invalid.as_posix()}")
    with invalid_engine.begin() as connection:
        connection.execute(
            text("UPDATE audit_logs SET target_label = :label"),
            {"label": "x" * 256},
        )
    invalid_engine.dispose()

    with pytest.raises(TargetDatabaseError):
        await migrate_sqlite_to_postgres(
            invalid,
            postgres_url=migrated_postgres_schema.database_url,
            credential_key=CREDENTIAL_KEY,
            target_schema=migrated_postgres_schema.name,
            backup_dir=tmp_path / "invalid-backup",
        )

    _create_empty_source_database(empty)
    unchanged = await migrate_sqlite_to_postgres(
        empty,
        postgres_url=migrated_postgres_schema.database_url,
        credential_key=CREDENTIAL_KEY,
        target_schema=migrated_postgres_schema.name,
        backup_dir=tmp_path / "empty-backup",
    )
    assert unchanged.status == "already_current"


@pytest.mark.asyncio
async def test_migration_creates_a_verified_backup_before_target_connection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)
    before = _sha256(source)
    backup_dir = tmp_path / "backups"

    with pytest.raises(TargetDatabaseError):
        await migrate_sqlite_to_postgres(
            source,
            postgres_url="postgresql+asyncpg://athena:secret@127.0.0.1:1/athena",
            credential_key=CREDENTIAL_KEY,
            backup_dir=backup_dir,
        )

    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert inspect_sqlite_source(
        backups[0],
        credential_key=CREDENTIAL_KEY,
    ).table_counts == inspect_sqlite_source(
        source,
        credential_key=CREDENTIAL_KEY,
    ).table_counts
    assert _sha256(source) == before


@pytest.mark.asyncio
async def test_migration_never_overwrites_an_existing_backup_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    source_digest = _sha256(source)
    collision = backup_dir / (
        f"athena-master-{source_digest[:16]}-{'0' * 31}1.db"
    )
    collision.write_bytes(b"previous-backup-evidence")
    generated_ids = iter((UUID(int=1), UUID(int=2)))
    monkeypatch.setattr(
        "app.cli.sqlite_postgres.uuid4",
        lambda: next(generated_ids),
    )

    with pytest.raises(TargetDatabaseError):
        await migrate_sqlite_to_postgres(
            source,
            postgres_url="postgresql+asyncpg://athena:secret@127.0.0.1:1/athena",
            credential_key=CREDENTIAL_KEY,
            backup_dir=backup_dir,
        )

    assert collision.read_bytes() == b"previous-backup-evidence"
    created_backups = sorted(backup_dir.glob("*.db"))
    assert len(created_backups) == 2
    assert created_backups[1].name.endswith(f"-{'0' * 31}2.db")


@pytest.mark.asyncio
async def test_migration_rejects_postgres_schema_names_longer_than_63_characters(
    tmp_path: Path,
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)

    with pytest.raises(TargetValidationError):
        await migrate_sqlite_to_postgres(
            source,
            postgres_url="postgresql+asyncpg://athena:secret@127.0.0.1:1/athena",
            credential_key=CREDENTIAL_KEY,
            target_schema="a" * 64,
            backup_dir=tmp_path / "backups",
        )

    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(
    "corruption_sql",
    [
        "ALTER TABLE users ALTER COLUMN username TYPE TEXT",
        "ALTER TABLE users ALTER COLUMN username DROP NOT NULL",
        "ALTER TABLE users DROP CONSTRAINT users_pkey",
        (
            "ALTER TABLE access_nodes "
            "DROP CONSTRAINT uq_access_nodes_token_fingerprint"
        ),
        "ALTER TABLE host_assets DROP CONSTRAINT host_assets_node_id_fkey",
    ],
    ids=["type", "nullable", "primary-key", "unique", "foreign-key"],
)
@pytest.mark.asyncio
async def test_target_with_forged_head_and_schema_drift_fails_closed(
    tmp_path: Path,
    migrated_postgres_schema: PostgresTestSchema,
    corruption_sql: str,
) -> None:
    source = tmp_path / "empty.db"
    _create_empty_source_database(source)
    engine = migrated_postgres_schema.create_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(text(corruption_sql))
    finally:
        await engine.dispose()

    with pytest.raises(TargetValidationError):
        await verify_postgres_import(
            source,
            postgres_url=migrated_postgres_schema.database_url,
            credential_key=CREDENTIAL_KEY,
            target_schema=migrated_postgres_schema.name,
        )


@pytest.mark.parametrize("corruption", ["wrong_key", "ciphertext", "fingerprint"])
@pytest.mark.asyncio
async def test_credential_preflight_fails_before_backup_or_postgres_connection(
    tmp_path: Path,
    corruption: str,
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)
    credential_key = CREDENTIAL_KEY
    if corruption == "wrong_key":
        credential_key = Fernet.generate_key().decode()
    else:
        engine = create_engine(f"sqlite:///{source.as_posix()}")
        with engine.begin() as connection:
            if corruption == "ciphertext":
                connection.execute(
                    text("UPDATE access_nodes SET encrypted_token = 'not-a-fernet-token'")
                )
            else:
                connection.execute(
                    text("UPDATE access_nodes SET token_fingerprint = :fingerprint"),
                    {"fingerprint": "0" * 64},
                )
        engine.dispose()
    before_sha256 = _sha256(source)
    before_stat = source.stat()

    with pytest.raises(SourceValidationError):
        await migrate_sqlite_to_postgres(
            source,
            postgres_url="postgresql+asyncpg://athena:secret@127.0.0.1:1/athena",
            credential_key=credential_key,
            backup_dir=tmp_path / "backups",
        )

    assert not (tmp_path / "backups").exists()
    assert _sha256(source) == before_sha256
    assert source.stat().st_size == before_stat.st_size
    assert source.stat().st_mtime_ns == before_stat.st_mtime_ns


@pytest.mark.parametrize("corruption", ["schema", "revision", "foreign_key"])
def test_source_schema_revision_and_foreign_keys_fail_closed_without_writes(
    tmp_path: Path,
    corruption: str,
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)
    engine = create_engine(f"sqlite:///{source.as_posix()}")
    with engine.begin() as connection:
        if corruption == "schema":
            connection.execute(text("ALTER TABLE users ADD COLUMN unexpected TEXT"))
        elif corruption == "revision":
            connection.execute(
                text(
                    "UPDATE alembic_version "
                    "SET version_num = '0007_node_lifecycle_management'"
                )
            )
        else:
            connection.execute(text("PRAGMA foreign_keys = OFF"))
            connection.execute(
                text(
                    "INSERT INTO host_assets "
                    "(node_id,host_id,name,address,port,username,tags,is_local) "
                    "VALUES "
                    "('missing-node','orphan-host','orphan','192.0.2.99',22,'root','[]',0)"
                )
            )
    engine.dispose()
    before_sha256 = _sha256(source)
    before_stat = source.stat()

    with pytest.raises(SourceValidationError):
        inspect_sqlite_source(source, credential_key=CREDENTIAL_KEY)

    assert _sha256(source) == before_sha256
    assert source.stat().st_size == before_stat.st_size
    assert source.stat().st_mtime_ns == before_stat.st_mtime_ns


def test_source_with_forged_head_and_wrong_column_type_fails_closed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "forged-head.db"
    _create_source_database(source)
    _rewrite_sqlite_table_definition(
        source,
        table_name="users",
        old="username VARCHAR(64) NOT NULL",
        new="username INTEGER NOT NULL",
    )
    before = _sha256(source)

    with pytest.raises(SourceValidationError):
        inspect_sqlite_source(source, credential_key=CREDENTIAL_KEY)

    assert _sha256(source) == before


@pytest.mark.parametrize(
    ("table_name", "old", "new"),
    [
        (
            "users",
            "username VARCHAR(64) NOT NULL",
            "username VARCHAR(64)",
        ),
        ("users", "PRIMARY KEY (id)", "UNIQUE (id)"),
        (
            "access_nodes",
            "UNIQUE (token_fingerprint)",
            "CHECK (length(token_fingerprint) >= 0)",
        ),
        (
            "host_assets",
            "FOREIGN KEY(node_id) REFERENCES access_nodes (node_id) ON DELETE CASCADE",
            "CHECK (length(node_id) >= 0)",
        ),
    ],
    ids=["nullable", "primary-key", "unique", "foreign-key"],
)
def test_source_with_forged_head_and_missing_constraint_fails_closed(
    tmp_path: Path,
    table_name: str,
    old: str,
    new: str,
) -> None:
    source = tmp_path / "forged-head.db"
    _create_source_database(source)
    _rewrite_sqlite_table_definition(
        source,
        table_name=table_name,
        old=old,
        new=new,
    )
    before = _sha256(source)

    with pytest.raises(SourceValidationError):
        inspect_sqlite_source(source, credential_key=CREDENTIAL_KEY)

    assert _sha256(source) == before


def test_migration_cli_requires_database_url_and_key_from_the_environment(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)

    exit_code = migrate_cli_main(
        ["--sqlite", str(source), "--backup-dir", str(tmp_path / "backups")],
        environ={},
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "CLI_CONFIGURATION_ERROR",
        "status": "error",
    }


def test_verification_cli_uses_the_same_environment_only_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)

    exit_code = verify_cli_main(["--sqlite", str(source)], environ={})

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "CLI_CONFIGURATION_ERROR",
        "status": "error",
    }


def test_cli_refuses_to_overwrite_an_existing_report_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)
    before = _sha256(source)

    exit_code = migrate_cli_main(
        [
            "--sqlite",
            str(source),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--report-json",
            str(source),
        ],
        environ={
            "ATHENA_MASTER_DATABASE_URL": (
                "postgresql+asyncpg://athena:secret-password@127.0.0.1:1/athena"
            ),
            "ATHENA_MASTER_CREDENTIAL_KEY": CREDENTIAL_KEY,
        },
    )

    output = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(output.out) == {
        "error_code": "REPORT_PATH_EXISTS",
        "status": "error",
    }
    assert "secret-password" not in output.out + output.err
    assert _sha256(source) == before
    assert not (tmp_path / "backups").exists()


def test_cli_report_never_overwrites_existing_backup_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "master.db"
    _create_source_database(source)
    existing_backup = tmp_path / "existing-backup.db"
    existing_backup.write_bytes(b"immutable-backup-evidence")

    exit_code = migrate_cli_main(
        [
            "--sqlite",
            str(source),
            "--backup-dir",
            str(tmp_path / "new-backups"),
            "--report-json",
            str(existing_backup),
        ],
        environ={
            "ATHENA_MASTER_DATABASE_URL": (
                "postgresql+asyncpg://athena:secret-password@127.0.0.1:1/athena"
            ),
            "ATHENA_MASTER_CREDENTIAL_KEY": CREDENTIAL_KEY,
        },
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "error_code": "REPORT_PATH_EXISTS",
        "status": "error",
    }
    assert existing_backup.read_bytes() == b"immutable-backup-evidence"
    assert not (tmp_path / "new-backups").exists()
