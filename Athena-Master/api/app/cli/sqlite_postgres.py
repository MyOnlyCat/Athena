from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import sqlite3
from collections.abc import Callable, Coroutine, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    Table,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.engine import Connection, Dialect, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app import models as _models  # noqa: F401
from app.core.database import Base
from app.core.postgres import is_safe_postgres_schema_name

EXPECTED_SOURCE_REVISION = "0008_operation_audit"


class MigrationError(RuntimeError):
    """A safe-to-display offline migration error."""

    code = "MIGRATION_ERROR"


class SourceValidationError(MigrationError):
    """The SQLite source cannot be imported safely."""

    code = "SOURCE_VALIDATION_FAILED"


class SourceChangedError(MigrationError):
    """The offline SQLite source changed while it was inspected."""

    code = "SOURCE_CHANGED"


class TargetValidationError(MigrationError):
    """The PostgreSQL destination is not safe to import into."""

    code = "TARGET_VALIDATION_FAILED"


class TargetConflictError(MigrationError):
    """The PostgreSQL destination contains different or partial data."""

    code = "TARGET_CONFLICT"


class ImportVerificationError(MigrationError):
    """The PostgreSQL import does not exactly match its SQLite source."""

    code = "IMPORT_VERIFICATION_FAILED"


class TargetDatabaseError(MigrationError):
    """PostgreSQL could not complete the requested migration operation."""

    code = "TARGET_DATABASE_ERROR"


class CliConfigurationError(MigrationError):
    """Required CLI environment configuration is absent."""

    code = "CLI_CONFIGURATION_ERROR"


class ValueKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    JSON_STRING_LIST = "json_string_list"
    BYTES = "bytes"
    UTC_DATETIME = "utc_datetime"


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    name: str
    kind: ValueKind
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class TableSpec:
    name: str
    columns: tuple[ColumnSpec, ...]
    primary_key: tuple[str, ...]
    copy_to_postgres: bool = True


@dataclass(frozen=True, slots=True)
class _SchemaColumn:
    name: str
    declared_type: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class _ForeignKeyContract:
    columns: tuple[str, ...]
    referred_table: str
    referred_columns: tuple[str, ...]
    ondelete: str | None


@dataclass(frozen=True, slots=True)
class _TableSchemaContract:
    columns: frozenset[_SchemaColumn]
    primary_key: tuple[str, ...]
    unique_columns: frozenset[tuple[str, ...]]
    foreign_keys: frozenset[_ForeignKeyContract]
    indexes: frozenset[tuple[tuple[str, ...], bool]]


def _column(
    name: str,
    kind: ValueKind = ValueKind.TEXT,
    *,
    nullable: bool = False,
) -> ColumnSpec:
    return ColumnSpec(name=name, kind=kind, nullable=nullable)


PHASE_ONE_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "users",
        (
            _column("id"),
            _column("username"),
            _column("normalized_username"),
            _column("password_hash"),
            _column("is_active", ValueKind.BOOLEAN),
            _column("auth_version", ValueKind.INTEGER),
            _column("last_login_at", ValueKind.UTC_DATETIME, nullable=True),
            _column("created_at", ValueKind.UTC_DATETIME),
            _column("updated_at", ValueKind.UTC_DATETIME),
        ),
        ("id",),
    ),
    TableSpec(
        "revoked_tokens",
        (
            _column("jti"),
            _column("expires_at", ValueKind.UTC_DATETIME),
        ),
        ("jti",),
    ),
    TableSpec(
        "registration_applications",
        (
            _column("id"),
            _column("node_id"),
            _column("reported_name"),
            _column("hostname"),
            _column("software_version"),
            _column("raw_body", ValueKind.BYTES),
            _column("request_path"),
            _column("auth_timestamp"),
            _column("auth_nonce"),
            _column("auth_signature"),
            _column("source_ip", nullable=True),
            _column("status"),
            _column("rejection_reason", nullable=True),
            _column("received_at", ValueKind.UTC_DATETIME),
            _column("status_changed_at", ValueKind.UTC_DATETIME),
        ),
        ("id",),
    ),
    TableSpec(
        "access_nodes",
        (
            _column("node_id"),
            _column("reported_name"),
            _column("hostname"),
            _column("software_version"),
            _column("management_status"),
            _column("display_name", nullable=True),
            _column("notes", nullable=True),
            _column("management_tags", ValueKind.JSON_STRING_LIST),
            _column("disable_reason", nullable=True),
            _column("encrypted_token"),
            _column("token_fingerprint", nullable=True),
            _column("approved_at", ValueKind.UTC_DATETIME),
            _column("last_heartbeat_at", ValueKind.UTC_DATETIME, nullable=True),
        ),
        ("node_id",),
    ),
    TableSpec(
        "audit_logs",
        (
            _column("id"),
            _column("actor_id", nullable=True),
            _column("actor_username", nullable=True),
            _column("action"),
            _column("target_type"),
            _column("target_id", nullable=True),
            _column("target_label", nullable=True),
            _column("result"),
            _column("source_ip", nullable=True),
            _column("error_code", nullable=True),
            _column("created_at", ValueKind.UTC_DATETIME),
        ),
        ("id",),
    ),
    TableSpec(
        "node_nonces",
        (
            _column("node_id"),
            _column("nonce"),
            _column("received_at", ValueKind.UTC_DATETIME),
        ),
        ("node_id", "nonce"),
    ),
    TableSpec(
        "host_assets",
        (
            _column("node_id"),
            _column("host_id"),
            _column("name"),
            _column("address"),
            _column("port", ValueKind.INTEGER),
            _column("username"),
            _column("tags", ValueKind.JSON_STRING_LIST),
            _column("is_local", ValueKind.BOOLEAN),
            _column("last_test_status", nullable=True),
            _column("last_test_code", nullable=True),
            _column("last_tested_at", ValueKind.UTC_DATETIME, nullable=True),
            _column("retired_at", ValueKind.UTC_DATETIME, nullable=True),
        ),
        ("node_id", "host_id"),
    ),
    TableSpec(
        "alembic_version",
        (_column("version_num"),),
        ("version_num",),
        copy_to_postgres=False,
    ),
)

_TABLES_BY_NAME = {table.name: table for table in PHASE_ONE_TABLES}
_EXPECTED_TABLE_NAMES = frozenset(_TABLES_BY_NAME)
_SQLITE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

type NormalizedValue = str | int | bool | bytes | datetime | list[str] | None
type NormalizedRow = dict[str, NormalizedValue]


@dataclass(frozen=True, slots=True)
class TableManifest:
    row_count: int
    sha256: str

    def to_dict(self) -> dict[str, str | int]:
        return {"rows": self.row_count, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class SourceInspection:
    source_sha256: str
    source_size: int
    source_mtime_ns: int
    source_revision: str
    source_unchanged: bool
    tables: dict[str, TableManifest]

    @property
    def table_counts(self) -> dict[str, int]:
        return {name: manifest.row_count for name, manifest in self.tables.items()}

    @property
    def table_digests(self) -> dict[str, str]:
        return {name: manifest.sha256 for name, manifest in self.tables.items()}

    def to_dict(self) -> dict[str, object]:
        return {
            "source": {
                "mtime_ns": self.source_mtime_ns,
                "revision": self.source_revision,
                "sha256": self.source_sha256,
                "size": self.source_size,
                "unchanged": self.source_unchanged,
            },
            "tables": {
                name: manifest.to_dict()
                for name, manifest in sorted(self.tables.items())
            },
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


@dataclass(frozen=True, slots=True)
class _SourceSnapshot:
    source_path: Path
    inspection: SourceInspection
    rows: dict[str, tuple[NormalizedRow, ...]]


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    algorithm: str
    tables: dict[str, TableManifest]

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm,
            "tables": {
                name: manifest.to_dict()
                for name, manifest in sorted(self.tables.items())
            },
        }


@dataclass(frozen=True, slots=True)
class MigrationReport:
    status: str
    source: SourceInspection
    target_schema: str
    target_revision: str
    backup_path: str | None = None
    backup_sha256: str | None = None
    verification: VerificationEvidence | None = None

    @property
    def source_sha256(self) -> str:
        return self.source.source_sha256

    @property
    def source_unchanged(self) -> bool:
        return self.source.source_unchanged

    @property
    def table_counts(self) -> dict[str, int]:
        return self.source.table_counts

    @property
    def table_digests(self) -> dict[str, str]:
        return self.source.table_digests

    def to_dict(self) -> dict[str, object]:
        report = self.source.to_dict()
        report["status"] = self.status
        report["target"] = {
            "revision": self.target_revision,
            "schema": self.target_schema,
        }
        if self.backup_path is not None and self.backup_sha256 is not None:
            report["backup"] = {
                "path": self.backup_path,
                "sha256": self.backup_sha256,
            }
        if self.verification is not None:
            report["verification"] = self.verification.to_dict()
        return report

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SourceValidationError("无法读取 SQLite 源文件") from exc
    return digest.hexdigest()


def _file_stat(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise SourceValidationError("无法检查 SQLite 源文件") from exc
    return stat.st_size, stat.st_mtime_ns


def _quote_sqlite_identifier(identifier: str) -> str:
    if not _SQLITE_IDENTIFIER.fullmatch(identifier):
        raise RuntimeError("invalid internal SQLite identifier")
    return f'"{identifier}"'


def _normalize_datetime(value: object, *, location: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise SourceValidationError(f"{location} 包含无效 UTC 时间") from exc
    else:
        raise SourceValidationError(f"{location} 包含无效 UTC 时间")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_value(value: object, column: ColumnSpec, *, table_name: str) -> NormalizedValue:
    location = f"表 {table_name} 的 {column.name} 列"
    if value is None:
        if not column.nullable:
            raise SourceValidationError(f"{location} 不允许为空")
        return None

    if column.kind is ValueKind.TEXT:
        if not isinstance(value, str):
            raise SourceValidationError(f"{location} 类型无效")
        return value
    if column.kind is ValueKind.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SourceValidationError(f"{location} 类型无效")
        return value
    if column.kind is ValueKind.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        raise SourceValidationError(f"{location} 包含无效布尔值")
    if column.kind is ValueKind.BYTES:
        if isinstance(value, bytes):
            return value
        if isinstance(value, memoryview):
            return value.tobytes()
        raise SourceValidationError(f"{location} 类型无效")
    if column.kind is ValueKind.UTC_DATETIME:
        return _normalize_datetime(value, location=location)
    if column.kind is ValueKind.JSON_STRING_LIST:
        try:
            decoded: Any = json.loads(value) if isinstance(value, (str, bytes)) else value
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceValidationError(f"{location} 包含无效 JSON") from exc
        if not isinstance(decoded, list) or any(not isinstance(item, str) for item in decoded):
            raise SourceValidationError(f"{location} 必须是字符串数组")
        return list(decoded)
    raise RuntimeError(f"unsupported internal value kind: {column.kind}")


def _canonical_bytes(value: NormalizedValue) -> bytes:
    if value is None:
        return b"N"
    if isinstance(value, bool):
        return b"T" if value else b"F"
    if isinstance(value, int):
        return b"I" + str(value).encode("ascii")
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC).isoformat(timespec="microseconds")
        return b"D" + normalized.replace("+00:00", "Z").encode("ascii")
    if isinstance(value, str):
        return b"S" + value.encode("utf-8")
    if isinstance(value, bytes):
        return b"B" + value
    if isinstance(value, list):
        return b"J" + json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    raise RuntimeError("unsupported normalized value")


def _manifest_for_rows(spec: TableSpec, rows: tuple[NormalizedRow, ...]) -> TableManifest:
    digest = hashlib.sha256()
    for row in rows:
        for column in spec.columns:
            name = column.name.encode("ascii")
            value = _canonical_bytes(row[column.name])
            digest.update(len(name).to_bytes(4, "big"))
            digest.update(name)
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return TableManifest(row_count=len(rows), sha256=digest.hexdigest())


def _normalize_declared_type(declared_type: object) -> str:
    return re.sub(r"\s+", " ", str(declared_type).strip().upper())


def _expected_table_contracts(*, dialect: Dialect) -> dict[str, _TableSchemaContract]:
    contracts: dict[str, _TableSchemaContract] = {}
    for table_name, table in Base.metadata.tables.items():
        columns = frozenset(
            _SchemaColumn(
                name=column.name,
                declared_type=_normalize_declared_type(
                    column.type.compile(dialect=dialect)
                ),
                nullable=bool(column.nullable),
            )
            for column in table.columns
        )
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        unique_columns.update(
            tuple(column.name for column in index.columns)
            for index in table.indexes
            if index.unique
        )
        foreign_keys = frozenset(
            _ForeignKeyContract(
                columns=tuple(element.parent.name for element in constraint.elements),
                referred_table=constraint.elements[0].column.table.name,
                referred_columns=tuple(
                    element.column.name for element in constraint.elements
                ),
                ondelete=(constraint.ondelete or "").upper() or None,
            )
            for constraint in table.foreign_key_constraints
        )
        contracts[table_name] = _TableSchemaContract(
            columns=columns,
            primary_key=tuple(column.name for column in table.primary_key.columns),
            unique_columns=frozenset(unique_columns),
            foreign_keys=foreign_keys,
            indexes=frozenset(
                (
                    tuple(column.name for column in index.columns),
                    bool(index.unique),
                )
                for index in table.indexes
            ),
        )
    contracts["alembic_version"] = _TableSchemaContract(
        columns=frozenset(
            (
                _SchemaColumn(
                    name="version_num",
                    declared_type="VARCHAR(32)",
                    nullable=False,
                ),
            )
        ),
        primary_key=("version_num",),
        unique_columns=frozenset(),
        foreign_keys=frozenset(),
        indexes=frozenset(),
    )
    return contracts


def _sqlite_table_contract(
    connection: sqlite3.Connection,
    *,
    table_name: str,
) -> _TableSchemaContract:
    quoted_table = _quote_sqlite_identifier(table_name)
    table_info = connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
    columns = frozenset(
        _SchemaColumn(
            name=str(row[1]),
            declared_type=_normalize_declared_type(row[2]),
            nullable=not bool(row[3]),
        )
        for row in table_info
    )
    primary_key = tuple(
        str(row[1])
        for row in sorted(table_info, key=lambda item: int(item[5]))
        if int(row[5]) > 0
    )

    unique_columns: set[tuple[str, ...]] = set()
    indexes: set[tuple[tuple[str, ...], bool]] = set()
    for index_row in connection.execute(f"PRAGMA index_list({quoted_table})"):
        index_name = _quote_sqlite_identifier(str(index_row[1]))
        index_columns = tuple(
            str(row[2])
            for row in sorted(
                connection.execute(f"PRAGMA index_info({index_name})").fetchall(),
                key=lambda item: int(item[0]),
            )
        )
        is_unique = bool(index_row[2])
        origin = str(index_row[3])
        if is_unique and origin != "pk":
            unique_columns.add(index_columns)
        if origin == "c":
            indexes.add((index_columns, is_unique))

    foreign_key_rows = connection.execute(
        f"PRAGMA foreign_key_list({quoted_table})"
    ).fetchall()
    grouped_foreign_keys: dict[int, list[sqlite3.Row]] = {}
    for row in foreign_key_rows:
        grouped_foreign_keys.setdefault(int(row[0]), []).append(row)
    foreign_keys = frozenset(
        _ForeignKeyContract(
            columns=tuple(str(row[3]) for row in sorted(rows, key=lambda item: item[1])),
            referred_table=str(rows[0][2]),
            referred_columns=tuple(
                str(row[4]) for row in sorted(rows, key=lambda item: item[1])
            ),
            ondelete=(str(rows[0][6]) or "").upper() or None,
        )
        for rows in grouped_foreign_keys.values()
    )
    return _TableSchemaContract(
        columns=columns,
        primary_key=primary_key,
        unique_columns=frozenset(unique_columns),
        foreign_keys=foreign_keys,
        indexes=frozenset(indexes),
    )


def _validate_sqlite_schema(connection: sqlite3.Connection) -> None:
    integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
    if [row[0] for row in integrity_rows] != ["ok"]:
        raise SourceValidationError("SQLite 源文件完整性检查失败")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise SourceValidationError("SQLite 源文件存在外键错误")

    actual_tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if actual_tables != _EXPECTED_TABLE_NAMES:
        raise SourceValidationError("SQLite 源文件表结构与 Phase 1 head 不一致")

    expected_contracts = _expected_table_contracts(dialect=sqlite_dialect.dialect())
    for table_name, expected_contract in expected_contracts.items():
        actual_contract = _sqlite_table_contract(
            connection,
            table_name=table_name,
        )
        if actual_contract != expected_contract:
            raise SourceValidationError(f"SQLite 表 {table_name} 的结构约束不一致")


def _inspection_column_names(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise TargetValidationError("PostgreSQL 目标包含无法验证的表达式列")
    return tuple(item for item in value if isinstance(item, str))


def _postgres_table_contract(
    connection: Connection,
    *,
    target_schema: str,
    table_name: str,
) -> _TableSchemaContract:
    inspector = sa_inspect(connection)
    inspected_columns = inspector.get_columns(table_name, schema=target_schema)
    columns = frozenset(
        _SchemaColumn(
            name=str(column["name"]),
            declared_type=_normalize_declared_type(
                column["type"].compile(dialect=connection.dialect)
            ),
            nullable=bool(column["nullable"]),
        )
        for column in inspected_columns
    )
    primary_key_info = inspector.get_pk_constraint(
        table_name,
        schema=target_schema,
    )
    primary_key = _inspection_column_names(
        primary_key_info.get("constrained_columns")
    )

    inspected_indexes = inspector.get_indexes(table_name, schema=target_schema)
    unique_columns = {
        _inspection_column_names(constraint.get("column_names"))
        for constraint in inspector.get_unique_constraints(
            table_name,
            schema=target_schema,
        )
    }
    unique_columns.update(
        _inspection_column_names(index.get("column_names"))
        for index in inspected_indexes
        if index.get("unique")
    )
    indexes = frozenset(
        (
            _inspection_column_names(index.get("column_names")),
            bool(index.get("unique")),
        )
        for index in inspected_indexes
        if not index.get("duplicates_constraint")
    )
    foreign_keys = frozenset(
        _ForeignKeyContract(
            columns=_inspection_column_names(
                foreign_key.get("constrained_columns")
            ),
            referred_table=str(foreign_key.get("referred_table")),
            referred_columns=_inspection_column_names(
                foreign_key.get("referred_columns")
            ),
            ondelete=(
                str((foreign_key.get("options") or {}).get("ondelete") or "").upper()
                or None
            ),
        )
        for foreign_key in inspector.get_foreign_keys(
            table_name,
            schema=target_schema,
        )
    )
    return _TableSchemaContract(
        columns=columns,
        primary_key=primary_key,
        unique_columns=frozenset(unique_columns),
        foreign_keys=foreign_keys,
        indexes=indexes,
    )


def _validate_postgres_schema_sync(
    connection: Connection,
    target_schema: str,
) -> None:
    inspector = sa_inspect(connection)
    actual_tables = set(inspector.get_table_names(schema=target_schema))
    if actual_tables != _EXPECTED_TABLE_NAMES:
        raise TargetValidationError("PostgreSQL 目标表结构与 Phase 1 head 不一致")
    expected_contracts = _expected_table_contracts(dialect=connection.dialect)
    for table_name, expected_contract in expected_contracts.items():
        actual_contract = _postgres_table_contract(
            connection,
            target_schema=target_schema,
            table_name=table_name,
        )
        if actual_contract != expected_contract:
            raise TargetValidationError(
                f"PostgreSQL 表 {table_name} 的结构约束与 Phase 1 head 不一致"
            )


async def _validate_postgres_schema(
    connection: AsyncConnection,
    *,
    target_schema: str,
) -> None:
    await connection.run_sync(_validate_postgres_schema_sync, target_schema)


def _read_sqlite_rows(
    connection: sqlite3.Connection,
    spec: TableSpec,
) -> tuple[NormalizedRow, ...]:
    quoted_columns = ", ".join(
        _quote_sqlite_identifier(column.name) for column in spec.columns
    )
    order_by = ", ".join(_quote_sqlite_identifier(name) for name in spec.primary_key)
    table_name = _quote_sqlite_identifier(spec.name)
    raw_rows = connection.execute(
        f"SELECT {quoted_columns} FROM {table_name} ORDER BY {order_by}"
    ).fetchall()
    return tuple(
        {
            column.name: _normalize_value(
                raw_row[column.name],
                column,
                table_name=spec.name,
            )
            for column in spec.columns
        }
        for raw_row in raw_rows
    )


def _validate_node_credentials(
    rows: tuple[NormalizedRow, ...],
    *,
    credential_key: str,
) -> None:
    try:
        cipher = Fernet(credential_key.encode())
    except (TypeError, ValueError) as exc:
        raise SourceValidationError("Credential Key 无效") from exc

    computed_fingerprints: set[str] = set()
    for row in rows:
        encrypted_token = row["encrypted_token"]
        stored_fingerprint = row["token_fingerprint"]
        if not isinstance(encrypted_token, str):
            raise SourceValidationError("Node Token 密文类型无效")
        try:
            token = cipher.decrypt(encrypted_token.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise SourceValidationError("Node Token 密文无法使用 Credential Key 解密") from exc
        fingerprint = hmac.new(
            credential_key.encode(),
            token.encode(),
            hashlib.sha256,
        ).hexdigest()
        if stored_fingerprint is not None and not hmac.compare_digest(
            str(stored_fingerprint),
            fingerprint,
        ):
            raise SourceValidationError("Node Token 指纹与密文不匹配")
        if fingerprint in computed_fingerprints:
            raise SourceValidationError("SQLite 源文件包含重复 Node Token")
        computed_fingerprints.add(fingerprint)


def _load_sqlite_source(
    sqlite_path: str | Path,
    *,
    credential_key: str,
) -> _SourceSnapshot:
    path = Path(sqlite_path).expanduser().resolve()
    if not path.is_file():
        raise SourceValidationError("SQLite 源文件不存在")
    before_size, before_mtime_ns = _file_stat(path)
    before_sha256 = _file_sha256(path)
    if _file_stat(path) != (before_size, before_mtime_ns):
        raise SourceChangedError("SQLite 源文件在计算摘要期间发生变化")
    uri = f"{path.as_uri()}?mode=ro"

    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise SourceValidationError("无法以只读模式打开 SQLite 源文件") from exc
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        _validate_sqlite_schema(connection)
        rows = {
            spec.name: _read_sqlite_rows(connection, spec)
            for spec in PHASE_ONE_TABLES
        }
        version_rows = rows["alembic_version"]
        if (
            len(version_rows) != 1
            or version_rows[0]["version_num"] != EXPECTED_SOURCE_REVISION
        ):
            raise SourceValidationError("SQLite 源文件不在 Phase 1 Alembic head")
        _validate_node_credentials(
            rows["access_nodes"],
            credential_key=credential_key,
        )
        connection.rollback()
    except sqlite3.Error as exc:
        raise SourceValidationError("读取 SQLite 源文件失败") from exc
    finally:
        connection.close()

    after_sha256 = _file_sha256(path)
    after_size, after_mtime_ns = _file_stat(path)
    if (
        after_sha256 != before_sha256
        or after_size != before_size
        or after_mtime_ns != before_mtime_ns
    ):
        raise SourceChangedError("SQLite 源文件在检查期间发生变化")
    manifests = {
        spec.name: _manifest_for_rows(spec, rows[spec.name])
        for spec in PHASE_ONE_TABLES
    }
    inspection = SourceInspection(
        source_sha256=before_sha256,
        source_size=before_size,
        source_mtime_ns=before_mtime_ns,
        source_revision=EXPECTED_SOURCE_REVISION,
        source_unchanged=True,
        tables=manifests,
    )
    return _SourceSnapshot(source_path=path, inspection=inspection, rows=rows)


def inspect_sqlite_source(
    sqlite_path: str | Path,
    *,
    credential_key: str,
) -> SourceInspection:
    """Validate a stopped Master SQLite database without modifying it."""

    return _load_sqlite_source(
        sqlite_path,
        credential_key=credential_key,
    ).inspection


def _create_verified_sqlite_backup(
    source: _SourceSnapshot,
    *,
    backup_dir: str | Path,
    credential_key: str,
) -> _SourceSnapshot:
    directory = Path(backup_dir).expanduser().resolve()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SourceValidationError("无法创建 SQLite 备份目录") from exc
    if not directory.is_dir():
        raise SourceValidationError("SQLite 备份目录无效")

    backup_path: Path | None = None
    for _ in range(16):
        candidate = directory / (
            f"athena-master-{source.inspection.source_sha256[:16]}-{uuid4().hex}.db"
        )
        try:
            descriptor = os.open(
                candidate,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.close(descriptor)
        except FileExistsError:
            continue
        except OSError as exc:
            raise SourceValidationError("无法安全创建 SQLite 备份文件") from exc
        backup_path = candidate
        break
    if backup_path is None:
        raise SourceValidationError("无法分配唯一的 SQLite 备份文件")
    source_uri = f"{source.source_path.as_uri()}?mode=ro"
    source_connection: sqlite3.Connection | None = None
    backup_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(source_uri, uri=True)
        source_connection.execute("PRAGMA query_only = ON")
        backup_connection = sqlite3.connect(backup_path)
        source_connection.backup(backup_connection)
    except (OSError, sqlite3.Error) as exc:
        backup_path.unlink(missing_ok=True)
        raise SourceValidationError("创建 SQLite 一致备份失败") from exc
    finally:
        if backup_connection is not None:
            backup_connection.close()
        if source_connection is not None:
            source_connection.close()

    try:
        backup = _load_sqlite_source(backup_path, credential_key=credential_key)
    except MigrationError:
        backup_path.unlink(missing_ok=True)
        raise
    if source.inspection.tables != backup.inspection.tables:
        backup_path.unlink(missing_ok=True)
        raise SourceValidationError("SQLite 备份内容与源文件不一致")
    _ensure_source_still_unchanged(source)
    return backup


def _validate_target_configuration(postgres_url: str, target_schema: str) -> None:
    try:
        driver_name = make_url(postgres_url).drivername
    except (TypeError, ValueError) as exc:
        raise TargetValidationError("PostgreSQL URL 无效") from exc
    if driver_name != "postgresql+asyncpg":
        raise TargetValidationError("PostgreSQL URL 必须使用 postgresql+asyncpg")
    if not is_safe_postgres_schema_name(target_schema):
        raise TargetValidationError("PostgreSQL 目标 schema 名称无效")


def _quote_postgres_identifier(connection: AsyncConnection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)


async def _configure_target_schema(
    connection: AsyncConnection,
    *,
    target_schema: str,
) -> None:
    quoted_schema = _quote_postgres_identifier(connection, target_schema)
    await connection.execute(text(f"SET LOCAL search_path TO {quoted_schema}, pg_catalog"))


async def _acquire_import_lock(
    connection: AsyncConnection,
    *,
    target_schema: str,
) -> None:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"athena:sqlite-import:{target_schema}"},
    )


async def _read_postgres_rows(
    connection: AsyncConnection,
    spec: TableSpec,
) -> tuple[NormalizedRow, ...]:
    if spec.name == "alembic_version":
        result = await connection.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    else:
        try:
            table = Base.metadata.tables[spec.name]
        except KeyError as exc:
            raise RuntimeError(f"missing ORM table metadata: {spec.name}") from exc
        result = await connection.execute(
            select(table).order_by(*(table.c[name] for name in spec.primary_key))
        )
    raw_rows = result.mappings().all()
    return tuple(
        {
            column.name: _normalize_value(
                raw_row[column.name],
                column,
                table_name=spec.name,
            )
            for column in spec.columns
        }
        for raw_row in raw_rows
    )


async def _read_postgres_snapshot(
    connection: AsyncConnection,
    *,
    credential_key: str,
) -> tuple[dict[str, tuple[NormalizedRow, ...]], dict[str, TableManifest]]:
    rows = {
        spec.name: await _read_postgres_rows(connection, spec)
        for spec in PHASE_ONE_TABLES
    }
    version_rows = rows["alembic_version"]
    if (
        len(version_rows) != 1
        or version_rows[0]["version_num"] != EXPECTED_SOURCE_REVISION
    ):
        raise TargetValidationError("PostgreSQL 目标不在 Phase 1 Alembic head")
    _validate_node_credentials(rows["access_nodes"], credential_key=credential_key)
    manifests = {
        spec.name: _manifest_for_rows(spec, rows[spec.name])
        for spec in PHASE_ONE_TABLES
    }
    return rows, manifests


def _verification_value_error(*, source: bool) -> NoReturn:
    error_type: type[MigrationError]
    if source:
        error_type = SourceValidationError
    else:
        error_type = ImportVerificationError
    raise error_type("独立校验遇到无法规范化的数据值")


def _verification_datetime(value: object, *, source: bool) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            _verification_value_error(source=source)
    else:
        _verification_value_error(source=source)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    normalized = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    return normalized.replace("+00:00", "Z")


def _verification_value(
    value: object,
    column: Column[Any],
    *,
    source: bool,
) -> object:
    if value is None:
        return ["null"]
    if isinstance(column.type, Boolean):
        if isinstance(value, bool):
            return ["boolean", value]
        if source and isinstance(value, int) and value in (0, 1):
            return ["boolean", bool(value)]
        _verification_value_error(source=source)
    if isinstance(column.type, Integer):
        if isinstance(value, bool) or not isinstance(value, int):
            _verification_value_error(source=source)
        return ["integer", value]
    if isinstance(column.type, DateTime):
        return ["utc-datetime", _verification_datetime(value, source=source)]
    if isinstance(column.type, LargeBinary):
        if isinstance(value, memoryview):
            value = value.tobytes()
        if not isinstance(value, bytes):
            _verification_value_error(source=source)
        return ["bytes-hex", value.hex()]
    if isinstance(column.type, JSON):
        decoded: object = value
        if isinstance(value, (str, bytes)):
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, UnicodeDecodeError):
                _verification_value_error(source=source)
        try:
            json.dumps(decoded, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            _verification_value_error(source=source)
        return ["json", decoded]
    if not isinstance(value, str):
        _verification_value_error(source=source)
    return ["text", value]


def _independent_manifest_for_rows(
    table: Table,
    rows: Iterable[Mapping[str, Any]],
    *,
    source: bool,
) -> TableManifest:
    digest = hashlib.sha256()
    digest.update(b"athena-offline-verification-v1\x00")
    digest.update(table.name.encode("ascii"))
    row_count = 0
    for row in rows:
        canonical_row = [
            [
                column.name,
                _verification_value(row[column.name], column, source=source),
            ]
            for column in table.columns
        ]
        payload = json.dumps(
            canonical_row,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        row_count += 1
    return TableManifest(row_count=row_count, sha256=digest.hexdigest())


def _read_independent_sqlite_manifests(
    source_path: Path,
) -> dict[str, TableManifest]:
    uri = f"{source_path.as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise SourceValidationError("独立校验无法以只读模式打开 SQLite 源文件") from exc
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        manifests: dict[str, TableManifest] = {}
        for table_name in sorted(Base.metadata.tables):
            table = Base.metadata.tables[table_name]
            quoted_columns = ", ".join(
                _quote_sqlite_identifier(column.name) for column in table.columns
            )
            order_by = ", ".join(
                _quote_sqlite_identifier(column.name)
                for column in table.primary_key.columns
            )
            quoted_table = _quote_sqlite_identifier(table_name)
            raw_rows = connection.execute(
                f"SELECT {quoted_columns} FROM {quoted_table} ORDER BY {order_by}"
            )
            rows = (
                {column.name: row[column.name] for column in table.columns}
                for row in raw_rows
            )
            manifests[table_name] = _independent_manifest_for_rows(
                table,
                rows,
                source=True,
            )
        connection.rollback()
    except sqlite3.Error as exc:
        raise SourceValidationError("独立校验读取 SQLite 源文件失败") from exc
    finally:
        connection.close()
    return manifests


async def _read_independent_postgres_manifests(
    connection: AsyncConnection,
    *,
    target_schema: str,
) -> dict[str, TableManifest]:
    quoted_schema = _quote_postgres_identifier(connection, target_schema)
    manifests: dict[str, TableManifest] = {}
    for table_name in sorted(Base.metadata.tables):
        table = Base.metadata.tables[table_name]
        quoted_columns = ", ".join(
            _quote_postgres_identifier(connection, column.name)
            for column in table.columns
        )
        order_by = ", ".join(
            _quote_postgres_identifier(connection, column.name)
            for column in table.primary_key.columns
        )
        quoted_table = _quote_postgres_identifier(connection, table_name)
        result = await connection.execute(
            text(
                f"SELECT {quoted_columns} FROM {quoted_schema}.{quoted_table} "
                f"ORDER BY {order_by}"
            )
        )
        rows = (
            {column.name: row[column.name] for column in table.columns}
            for row in result.mappings()
        )
        manifests[table_name] = _independent_manifest_for_rows(
            table,
            rows,
            source=False,
        )
    return manifests


async def _verify_independent_import(
    source_path: Path,
    connection: AsyncConnection,
    *,
    target_schema: str,
) -> VerificationEvidence:
    source_manifests = _read_independent_sqlite_manifests(source_path)
    target_manifests = await _read_independent_postgres_manifests(
        connection,
        target_schema=target_schema,
    )
    if source_manifests != target_manifests:
        raise ImportVerificationError("PostgreSQL 数据未通过独立 SQL 清单校验")
    return VerificationEvidence(
        algorithm="athena-offline-verification-v1",
        tables=target_manifests,
    )


def _data_manifests(
    manifests: dict[str, TableManifest],
) -> dict[str, TableManifest]:
    return {
        spec.name: manifests[spec.name]
        for spec in PHASE_ONE_TABLES
        if spec.copy_to_postgres
    }


def _target_is_empty(manifests: dict[str, TableManifest]) -> bool:
    return all(manifest.row_count == 0 for manifest in _data_manifests(manifests).values())


def _matches_source(
    source: SourceInspection,
    target_manifests: dict[str, TableManifest],
) -> bool:
    return source.tables == target_manifests


async def _insert_source_rows(
    connection: AsyncConnection,
    source: _SourceSnapshot,
) -> None:
    batch_size = 500
    for spec in PHASE_ONE_TABLES:
        if not spec.copy_to_postgres:
            continue
        table = Base.metadata.tables[spec.name]
        rows = source.rows[spec.name]
        for offset in range(0, len(rows), batch_size):
            batch = [dict(row) for row in rows[offset : offset + batch_size]]
            if batch:
                await connection.execute(table.insert(), batch)


def _ensure_source_still_unchanged(source: _SourceSnapshot) -> None:
    size, mtime_ns = _file_stat(source.source_path)
    if (
        size != source.inspection.source_size
        or mtime_ns != source.inspection.source_mtime_ns
        or _file_sha256(source.source_path) != source.inspection.source_sha256
    ):
        raise SourceChangedError("SQLite 源文件在迁移期间发生变化")


async def migrate_sqlite_to_postgres(
    sqlite_path: str | Path,
    *,
    postgres_url: str,
    credential_key: str,
    target_schema: str = "public",
    backup_dir: str | Path,
) -> MigrationReport:
    """Import a stopped Master SQLite database in one PostgreSQL transaction."""

    _validate_target_configuration(postgres_url, target_schema)
    source = _load_sqlite_source(sqlite_path, credential_key=credential_key)
    backup = _create_verified_sqlite_backup(
        source,
        backup_dir=backup_dir,
        credential_key=credential_key,
    )
    engine = create_async_engine(
        postgres_url,
        hide_parameters=True,
        poolclass=NullPool,
    )
    status: str | None = None
    verification: VerificationEvidence | None = None
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY")
            )
            await _configure_target_schema(
                connection,
                target_schema=target_schema,
            )
            await _validate_postgres_schema(
                connection,
                target_schema=target_schema,
            )
            _, before_manifests = await _read_postgres_snapshot(
                connection,
                credential_key=credential_key,
            )
            if _matches_source(source.inspection, before_manifests):
                verification = await _verify_independent_import(
                    source.source_path,
                    connection,
                    target_schema=target_schema,
                )
                status = "already_current"
                _ensure_source_still_unchanged(source)
                _ensure_source_still_unchanged(backup)
            elif not _target_is_empty(before_manifests):
                raise TargetConflictError("PostgreSQL 目标包含部分或不同的数据")

        if status is None:
            async with engine.begin() as connection:
                await connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                )
                await _configure_target_schema(
                    connection,
                    target_schema=target_schema,
                )
                await _validate_postgres_schema(
                    connection,
                    target_schema=target_schema,
                )
                await _acquire_import_lock(
                    connection,
                    target_schema=target_schema,
                )
                _, locked_manifests = await _read_postgres_snapshot(
                    connection,
                    credential_key=credential_key,
                )
                if _matches_source(source.inspection, locked_manifests):
                    status = "already_current"
                elif not _target_is_empty(locked_manifests):
                    raise TargetConflictError("PostgreSQL 目标包含部分或不同的数据")
                else:
                    await _insert_source_rows(connection, backup)
                    status = "imported"
                _, after_manifests = await _read_postgres_snapshot(
                    connection,
                    credential_key=credential_key,
                )
                if not _matches_source(source.inspection, after_manifests):
                    raise ImportVerificationError("PostgreSQL 导入结果与 SQLite 源不一致")
                verification = await _verify_independent_import(
                    source.source_path,
                    connection,
                    target_schema=target_schema,
                )
                _ensure_source_still_unchanged(source)
                _ensure_source_still_unchanged(backup)
    except MigrationError:
        raise
    except Exception as error:
        raise TargetDatabaseError("PostgreSQL 离线导入失败") from error
    finally:
        await engine.dispose()

    if status is None or verification is None:
        raise RuntimeError("migration completed without a status")
    return MigrationReport(
        status=status,
        source=source.inspection,
        target_schema=target_schema,
        target_revision=EXPECTED_SOURCE_REVISION,
        backup_path=str(backup.source_path),
        backup_sha256=backup.inspection.source_sha256,
        verification=verification,
    )


async def verify_postgres_import(
    sqlite_path: str | Path,
    *,
    postgres_url: str,
    credential_key: str,
    target_schema: str = "public",
) -> MigrationReport:
    """Independently verify PostgreSQL against a read-only SQLite source."""

    _validate_target_configuration(postgres_url, target_schema)
    source = _load_sqlite_source(sqlite_path, credential_key=credential_key)
    engine = create_async_engine(
        postgres_url,
        hide_parameters=True,
        poolclass=NullPool,
    )
    verification: VerificationEvidence | None = None
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            )
            await _configure_target_schema(
                connection,
                target_schema=target_schema,
            )
            await _validate_postgres_schema(
                connection,
                target_schema=target_schema,
            )
            _, target_manifests = await _read_postgres_snapshot(
                connection,
                credential_key=credential_key,
            )
            if not _matches_source(source.inspection, target_manifests):
                raise ImportVerificationError("PostgreSQL 数据与 SQLite 源不一致")
            verification = await _verify_independent_import(
                source.source_path,
                connection,
                target_schema=target_schema,
            )
            _ensure_source_still_unchanged(source)
    except MigrationError:
        raise
    except Exception as error:
        raise TargetDatabaseError("PostgreSQL 离线导入校验失败") from error
    finally:
        await engine.dispose()

    if verification is None:
        raise RuntimeError("verification completed without evidence")
    return MigrationReport(
        status="verified",
        source=source.inspection,
        target_schema=target_schema,
        target_revision=EXPECTED_SOURCE_REVISION,
        verification=verification,
    )


type OfflineOperation = Callable[..., Coroutine[Any, Any, MigrationReport]]


def _serialize_cli_payload(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _write_cli_payload(payload: dict[str, object]) -> str:
    serialized = _serialize_cli_payload(payload)
    print(serialized)
    return serialized


def run_offline_cli(
    operation: OfflineOperation,
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    program: str,
    require_backup: bool = False,
) -> int:
    """Run a migration operation without accepting database secrets as arguments."""

    parser = argparse.ArgumentParser(prog=program)
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--schema", default="public")
    parser.add_argument("--backup-dir", required=require_backup, type=Path)
    parser.add_argument("--report-json", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.report_json is not None and arguments.report_json.exists():
        _write_cli_payload({"error_code": "REPORT_PATH_EXISTS", "status": "error"})
        return 2
    active_environment = os.environ if environ is None else environ
    postgres_url = active_environment.get("ATHENA_MASTER_DATABASE_URL", "").strip()
    credential_key = active_environment.get("ATHENA_MASTER_CREDENTIAL_KEY", "").strip()
    if not postgres_url or not credential_key:
        _write_cli_payload(
            {
                "error_code": CliConfigurationError.code,
                "status": "error",
            }
        )
        return 2

    try:
        operation_arguments: dict[str, object] = {
            "postgres_url": postgres_url,
            "credential_key": credential_key,
            "target_schema": arguments.schema,
        }
        if require_backup:
            operation_arguments["backup_dir"] = arguments.backup_dir
        report: MigrationReport = asyncio.run(
            operation(arguments.sqlite, **operation_arguments)
        )
    except MigrationError as exc:
        _write_cli_payload({"error_code": exc.code, "status": "error"})
        return 1
    except Exception:
        _write_cli_payload({"error_code": "UNEXPECTED_ERROR", "status": "error"})
        return 1

    report_payload = report.to_dict()
    serialized = _serialize_cli_payload(report_payload)
    if arguments.report_json is not None:
        try:
            descriptor = os.open(
                arguments.report_json,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as report_file:
                report_file.write(f"{serialized}\n")
        except OSError:
            _write_cli_payload({"error_code": "REPORT_WRITE_FAILED", "status": "error"})
            return 1
    print(serialized)
    return 0
