import re

DEFAULT_STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_IDLE_TRANSACTION_TIMEOUT_MS = 60_000
DEFAULT_LOCK_TIMEOUT_MS = 10_000
_POSTGRES_SCHEMA_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


def is_safe_postgres_schema_name(value: str) -> bool:
    return _POSTGRES_SCHEMA_NAME.fullmatch(value) is not None


def postgres_server_settings(
    *,
    schema: str,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    idle_transaction_timeout_ms: int = DEFAULT_IDLE_TRANSACTION_TIMEOUT_MS,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
) -> dict[str, str]:
    """Build the asyncpg settings shared by the runtime and Alembic."""

    timeout_values = (
        statement_timeout_ms,
        idle_transaction_timeout_ms,
        lock_timeout_ms,
    )
    if any(value < 1 for value in timeout_values):
        raise ValueError("PostgreSQL timeout values must be positive")
    return {
        "timezone": "UTC",
        "statement_timeout": str(statement_timeout_ms),
        "idle_in_transaction_session_timeout": str(idle_transaction_timeout_ms),
        "lock_timeout": str(lock_timeout_ms),
        "search_path": schema,
    }
