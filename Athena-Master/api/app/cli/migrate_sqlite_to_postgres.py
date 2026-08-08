from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.cli.sqlite_postgres import migrate_sqlite_to_postgres, run_offline_cli


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    return run_offline_cli(
        migrate_sqlite_to_postgres,
        argv,
        environ=environ,
        program="python -m app.cli.migrate_sqlite_to_postgres",
        require_backup=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
