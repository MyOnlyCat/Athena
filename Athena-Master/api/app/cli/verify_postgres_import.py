from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.cli.sqlite_postgres import run_offline_cli, verify_postgres_import


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    return run_offline_cli(
        verify_postgres_import,
        argv,
        environ=environ,
        program="python -m app.cli.verify_postgres_import",
    )


if __name__ == "__main__":
    raise SystemExit(main())
