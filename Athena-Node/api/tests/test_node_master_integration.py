import asyncio
import base64
import os
import re
import secrets
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.services.inventory_sync import InventorySynchronizer, build_inventory
from app.services.master_client import MasterClient
from app.services.signing import sign_request

HEARTBEAT_PATH = "/api/node/v1/nodes/heartbeat"
MIN_HEARTBEAT_INTERVAL_SECONDS = 10
MASTER_API_ROOT = Path(__file__).resolve().parents[3] / "Athena-Master" / "api"
MASTER_USERNAME = "admin"
MASTER_PASSWORD = "MasterIntegrationPassw0rd!"
NODE_USERNAME = "admin"
NODE_PASSWORD = "NodeIntegrationPassw0rd!"
CREDENTIAL_KEY = "4UlSOndzr4KYLmDMK5T5OmRsWLOtqzmNe01_sucGm2o="
MASTER_SCHEMA_PATTERN = re.compile(r"athena_node_test_[0-9a-f]{32}")
MASTER_SCHEMA_COMMAND = r"""
import asyncio
import os
import re
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    operation, schema = sys.argv[1:]
    if re.fullmatch(r"athena_node_test_[0-9a-f]{32}", schema) is None:
        raise RuntimeError("unsafe integration schema")
    engine = create_async_engine(
        os.environ["ATHENA_TEST_POSTGRES_URL"],
        hide_parameters=True,
    )
    try:
        async with engine.begin() as connection:
            quoted = connection.dialect.identifier_preparer.quote(schema)
            if operation == "create":
                await connection.execute(text(f"CREATE SCHEMA {quoted}"))
            elif operation == "drop":
                await connection.execute(text(f"DROP SCHEMA {quoted} CASCADE"))
            else:
                raise RuntimeError("unsupported schema operation")
    finally:
        await engine.dispose()


asyncio.run(main())
"""


class _RedactedEnvironment(dict[str, str]):
    def __repr__(self) -> str:
        return "<redacted Master subprocess environment>"

    def __str__(self) -> str:
        return self.__repr__()


def _base64url_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _master_python() -> Path:
    candidates = (
        MASTER_API_ROOT / ".venv" / "Scripts" / "python.exe",
        MASTER_API_ROOT / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    pytest.fail("Master virtual-environment Python is required for this integration test")


def _test_postgres_url() -> str:
    database_url = os.environ.get("ATHENA_TEST_POSTGRES_URL", "").strip()
    if not database_url:
        pytest.fail("ATHENA_TEST_POSTGRES_URL is required for this integration test")
    if not database_url.startswith("postgresql+asyncpg://"):
        pytest.fail("ATHENA_TEST_POSTGRES_URL must use postgresql+asyncpg")
    return database_url


def _master_schema_name() -> str:
    schema = f"athena_node_test_{secrets.token_hex(16)}"
    if MASTER_SCHEMA_PATTERN.fullmatch(schema) is None:
        raise AssertionError("generated an unsafe Master integration schema")
    return schema


def _validate_master_schema(schema: str) -> None:
    if MASTER_SCHEMA_PATTERN.fullmatch(schema) is None:
        raise ValueError("refusing an unsafe Master integration schema")


def _master_environment(tmp_path: Path, schema: str) -> _RedactedEnvironment:
    _validate_master_schema(schema)
    data_dir = (tmp_path / "master-data").resolve()
    data_dir.mkdir()
    environment = _RedactedEnvironment(os.environ.copy())
    environment.update(
        {
            "ATHENA_MASTER_ENVIRONMENT": "test",
            "ATHENA_MASTER_DATABASE_URL": _test_postgres_url(),
            "ATHENA_MASTER_DATABASE_SCHEMA": schema,
            "ATHENA_MASTER_JWT_SECRET": "master-integration-jwt-secret-32-characters",
            "ATHENA_MASTER_CREDENTIAL_KEY": CREDENTIAL_KEY,
            "ATHENA_MASTER_BOOTSTRAP_USERNAME": MASTER_USERNAME,
            "ATHENA_MASTER_BOOTSTRAP_PASSWORD": MASTER_PASSWORD,
            "ATHENA_MASTER_DATA_DIR": str(data_dir),
            "PYTHONIOENCODING": "utf-8",
            # The subprocess must import Master, even when this pytest process has
            # Athena-Node/api at the front of sys.path under the shared `app` name.
            "PYTHONPATH": str(MASTER_API_ROOT),
        }
    )
    return environment


def _redact_master_output(output: str, environment: _RedactedEnvironment) -> str:
    redacted = output
    database_url = environment.get("ATHENA_TEST_POSTGRES_URL", "")
    sensitive_values = {
        database_url,
        environment.get("ATHENA_MASTER_DATABASE_URL", ""),
        environment.get("ATHENA_MASTER_CREDENTIAL_KEY", ""),
        environment.get("ATHENA_MASTER_JWT_SECRET", ""),
        environment.get("ATHENA_MASTER_BOOTSTRAP_PASSWORD", ""),
    }
    if database_url:
        try:
            parsed = urlsplit(database_url)
        except ValueError:
            parsed = None
        if parsed is not None:
            sensitive_values.update(
                {
                    parsed.username or "",
                    parsed.password or "",
                    unquote(parsed.username or ""),
                    unquote(parsed.password or ""),
                    database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
                }
            )
    for value in sorted((item for item in sensitive_values if item), key=len, reverse=True):
        redacted = redacted.replace(value, "<redacted>")
    return redacted or "<no subprocess output>"


def _run_master_command(
    master_python: Path,
    arguments: list[str],
    environment: _RedactedEnvironment,
    *,
    operation: str,
) -> None:
    try:
        completed = subprocess.run(
            [str(master_python), *arguments],
            cwd=MASTER_API_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{operation} timed out; subprocess output was withheld")
    except OSError:
        pytest.fail(f"{operation} could not start; subprocess output was withheld")
    if completed.returncode != 0:
        pytest.fail(
            f"{operation} failed\n"
            f"stdout:\n{_redact_master_output(completed.stdout, environment)}\n"
            f"stderr:\n{_redact_master_output(completed.stderr, environment)}"
        )


def _run_master_schema_command(
    master_python: Path,
    environment: _RedactedEnvironment,
    schema: str,
    operation: str,
) -> None:
    _validate_master_schema(schema)
    _run_master_command(
        master_python,
        ["-c", MASTER_SCHEMA_COMMAND, operation, schema],
        environment,
        operation=f"Master test schema {operation}",
    )


def _run_master_migrations(
    master_python: Path,
    environment: _RedactedEnvironment,
) -> None:
    _run_master_command(
        master_python,
        ["-m", "alembic", "upgrade", "head"],
        environment,
        operation="Master migration",
    )


def _wait_for_master(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    last_error: Exception | None = None
    with httpx.Client(base_url=base_url, timeout=0.5, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Master exited during startup with code {process.returncode}"
                )
            try:
                response = client.get("/api/v1/health")
                if response.status_code == 200 and response.json() == {
                    "status": "ok",
                    "service": "athena-master-api",
                    "database": "ok",
                }:
                    return
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
            time.sleep(0.05)
    raise TimeoutError(f"Master health check timed out; last error: {last_error!r}")


def _stop_process(
    process: subprocess.Popen[str],
    environment: _RedactedEnvironment,
) -> str:
    if process.poll() is None:
        process.terminate()
    try:
        output, _ = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate(timeout=5)
    return _redact_master_output(output, environment)


@contextmanager
def _running_master(tmp_path: Path) -> Iterator[str]:
    schema = _master_schema_name()
    environment = _master_environment(tmp_path, schema)
    master_python = _master_python()
    process: subprocess.Popen[str] | None = None
    schema_created = False
    active_error: BaseException | None = None
    try:
        try:
            _run_master_schema_command(
                master_python,
                environment,
                schema,
                "create",
            )
            schema_created = True
            _run_master_migrations(master_python, environment)
            port = _free_local_port()
            base_url = f"http://127.0.0.1:{port}"
            try:
                process = subprocess.Popen(
                    [
                        str(master_python),
                        "-m",
                        "uvicorn",
                        "app.main:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--workers",
                        "1",
                        "--log-level",
                        "warning",
                    ],
                    cwd=MASTER_API_ROOT,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                pytest.fail("Master process could not start; subprocess output was withheld")
            _wait_for_master(base_url, process)
            yield base_url
        except BaseException as exc:
            active_error = exc
            raise
    finally:
        process_error: AssertionError | None = None
        if process is not None:
            exited_early = process.poll() is not None
            output = _stop_process(process, environment)
            if active_error is not None:
                active_error.add_note(f"Master subprocess output:\n{output}")
            elif exited_early:
                process_error = AssertionError(
                    f"Master exited unexpectedly with code {process.returncode}\n{output}"
                )
        if schema_created:
            try:
                _run_master_schema_command(
                    master_python,
                    environment,
                    schema,
                    "drop",
                )
            except BaseException as cleanup_error:
                if active_error is not None:
                    active_error.add_note(
                        "Master test schema cleanup failed; sensitive output was withheld"
                    )
                elif process_error is not None:
                    process_error.add_note(
                        "Master test schema cleanup failed; sensitive output was withheld"
                    )
                else:
                    raise cleanup_error
        if process_error is not None:
            raise process_error


@asynccontextmanager
async def _node_client(
    settings: Settings,
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient, dict[str, str]]]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://node.local",
            trust_env=False,
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": NODE_USERNAME, "password": NODE_PASSWORD},
            )
            assert login.status_code == 200, login.text
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            yield app, client, headers


async def _master_login(client: httpx.AsyncClient) -> dict[str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": MASTER_USERNAME, "password": MASTER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _master_state(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    node_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = await client.get("/api/v1/nodes", headers=headers)
    assets = await client.get(f"/api/v1/nodes/{node_id}/assets", headers=headers)
    assert nodes.status_code == 200, nodes.text
    assert assets.status_code == 200, assets.text
    assert nodes.json()["total"] == 1
    return dict(nodes.json()["items"][0]), dict(assets.json())


def _signed_heartbeat_headers(
    *,
    body: bytes,
    node_id: str,
    token: str,
    nonce: str,
    timestamp: str | None = None,
) -> dict[str, str]:
    effective_timestamp = timestamp or str(int(time.time()))
    return {
        "Content-Type": "application/json",
        "X-Node-Id": node_id,
        "X-Timestamp": effective_timestamp,
        "X-Nonce": nonce,
        "X-Signature": sign_request(
            secret=token,
            method="POST",
            path_with_query=HEARTBEAT_PATH,
            timestamp=effective_timestamp,
            nonce=nonce,
            body=body,
        ),
    }


async def _wait_for_next_heartbeat(accepted_at: float) -> None:
    remaining = MIN_HEARTBEAT_INTERVAL_SECONDS + 0.15 - (
        time.monotonic() - accepted_at
    )
    if remaining > 0:
        await asyncio.sleep(remaining)


def _assert_sync_status(sync: InventorySynchronizer, expected: str) -> None:
    assert sync.status == expected


def _assert_complete_assets(
    page: dict[str, Any],
    *,
    node_id: str,
    host_a: dict[str, Any],
    host_b: dict[str, Any],
    b_lifecycle: str,
) -> None:
    assert page["total"] == 2
    assets = {item["host_id"]: item for item in page["items"]}
    assert assets[host_a["id"]] == {
        "node_id": node_id,
        "host_id": host_a["id"],
        "name": "db-01",
        "address": "10.20.0.11",
        "port": 2222,
        "username": "deploy-a",
        "tags": ["database", "production"],
        "is_local": True,
        "last_test_status": None,
        "last_test_code": None,
        "last_tested_at": None,
        "lifecycle_status": "active",
        "retired_at": None,
        "source_node_connectivity_status": "online",
    }
    assert assets[host_b["id"]] == {
        "node_id": node_id,
        "host_id": host_b["id"],
        "name": "web-01",
        "address": "10.20.0.12",
        "port": 22,
        "username": "deploy-b",
        "tags": ["web", "production"],
        "is_local": False,
        "last_test_status": None,
        "last_test_code": None,
        "last_tested_at": None,
        "lifecycle_status": b_lifecycle,
        "retired_at": (
            assets[host_b["id"]]["retired_at"]
            if b_lifecycle == "retired"
            else None
        ),
        "source_node_connectivity_status": "online",
    }
    if b_lifecycle == "retired":
        assert assets[host_b["id"]]["retired_at"].endswith("Z")


@pytest.mark.asyncio
async def test_node_master_registration_inventory_and_lifecycle_over_real_tcp(
    tmp_path: Path,
) -> None:
    token = _base64url_token()
    wrong_token = _base64url_token()
    assert token != wrong_token
    node_settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'node.db').as_posix()}",
        jwt_secret="node-integration-jwt-secret-32-characters",
        credential_key=CREDENTIAL_KEY,
        bootstrap_username=NODE_USERNAME,
        bootstrap_password=NODE_PASSWORD,
        node_name="Integration Node",
        data_dir=tmp_path / "node-data",
    )

    with _running_master(tmp_path) as master_url:
        port = int(master_url.rsplit(":", 1)[1])
        async with httpx.AsyncClient(
            base_url=master_url,
            timeout=5,
            trust_env=False,
        ) as master:
            master_headers = await _master_login(master)

            async with _node_client(node_settings) as (_, node, node_headers):
                connection = {
                    "scheme": "http",
                    "host": "127.0.0.1",
                    "port": port,
                    "token": token,
                }
                tested = await node.post(
                    "/api/v1/master-settings/test",
                    headers=node_headers,
                    json=connection,
                )
                saved = await node.put(
                    "/api/v1/master-settings",
                    headers=node_headers,
                    json=connection,
                )
                assert tested.status_code == 200, tested.text
                assert tested.json() == {"status": "success"}
                assert saved.status_code == 200, saved.text
                assert saved.json()["has_token"] is True
                assert token not in saved.text
                node_id = str(saved.json()["node_id"])

                host_a_response = await node.post(
                    "/api/v1/hosts",
                    headers=node_headers,
                    json={
                        "name": "db-01",
                        "address": "10.20.0.11",
                        "port": 2222,
                        "username": "deploy-a",
                        "password": "local-secret-a",
                        "tags": ["database", "production"],
                        "is_local": True,
                    },
                )
                host_b_response = await node.post(
                    "/api/v1/hosts",
                    headers=node_headers,
                    json={
                        "name": "web-01",
                        "address": "10.20.0.12",
                        "port": 22,
                        "username": "deploy-b",
                        "password": "local-secret-b",
                        "tags": ["web", "production"],
                        "is_local": False,
                    },
                )
                assert host_a_response.status_code == 201, host_a_response.text
                assert host_b_response.status_code == 201, host_b_response.text
                host_a = dict(host_a_response.json())
                host_b = dict(host_b_response.json())

                submitted = await node.post(
                    "/api/v1/master-settings/registration",
                    headers=node_headers,
                )
                assert submitted.status_code == 202, submitted.text
                assert submitted.json() == {"status": "pending"}

            applications = await master.get(
                "/api/v1/registration-applications",
                headers=master_headers,
            )
            assert applications.status_code == 200, applications.text
            assert applications.json()["total"] == 1
            application = applications.json()["items"][0]
            assert application["node_id"] == node_id
            assert application["status"] == "pending"
            assert application["identity_verified"] is False

            wrong_approval = await master.post(
                f"/api/v1/registration-applications/{application['id']}/approve",
                headers=master_headers,
                json={"token": wrong_token},
            )
            still_pending = await master.get(
                "/api/v1/registration-applications",
                headers=master_headers,
            )
            assert (wrong_approval.status_code, wrong_approval.json()["code"]) == (
                401,
                "REGISTRATION_TOKEN_INVALID",
            )
            assert still_pending.json()["items"][0] == application
            assert (await master.get("/api/v1/nodes", headers=master_headers)).json()[
                "total"
            ] == 0

            approved = await master.post(
                f"/api/v1/registration-applications/{application['id']}/approve",
                headers=master_headers,
                json={"token": token},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["node_id"] == node_id
            assert approved.json()["management_status"] == "active"
            assert token not in approved.text

            # Recreating the Node app over the same SQLite file proves both the
            # generated UUIDv7 identity and the encrypted Master token persisted.
            async with _node_client(node_settings) as (app, node, node_headers):
                loaded = await node.get("/api/v1/master-settings", headers=node_headers)
                assert loaded.status_code == 200, loaded.text
                assert loaded.json()["node_id"] == node_id
                assert loaded.json()["has_token"] is True
                assert loaded.json()["registration_status"] == "pending"
                assert token not in loaded.text

                synchronized = await node.post(
                    "/api/v1/master-settings/registration/status",
                    headers=node_headers,
                )
                assert synchronized.status_code == 200, synchronized.text
                assert synchronized.json() == {"status": "approved"}

                sync = app.state.inventory_sync
                assert isinstance(sync, InventorySynchronizer)
                assert isinstance(sync.master_client, MasterClient)
                captured: list[tuple[bytes, dict[str, str]]] = []

                async def capture_heartbeat(request: httpx.Request) -> None:
                    if request.url.path == HEARTBEAT_PATH:
                        body = await request.aread()
                        captured.append(
                            (
                                body,
                                {
                                    name: request.headers[name]
                                    for name in (
                                        "Content-Type",
                                        "X-Node-Id",
                                        "X-Timestamp",
                                        "X-Nonce",
                                        "X-Signature",
                                    )
                                },
                            )
                        )

                sync.master_client.http.event_hooks["request"].append(capture_heartbeat)
                await sync.sync_now()
                first_accepted_at = time.monotonic()
                _assert_sync_status(sync, "online")
                assert len(captured) == 1

                initial_node, initial_assets = await _master_state(
                    master,
                    master_headers,
                    node_id,
                )
                assert initial_node["node_id"] == node_id
                assert initial_node["reported_name"] == "Integration Node"
                assert initial_node["software_version"] == node_settings.node_version
                assert initial_node["management_status"] == "active"
                assert initial_node["connectivity_status"] == "online"
                _assert_complete_assets(
                    initial_assets,
                    node_id=node_id,
                    host_a=host_a,
                    host_b=host_b,
                    b_lifecycle="active",
                )
                assert "local-secret" not in str(initial_assets)

                original_body, original_headers = captured[0]
                replayed = await master.post(
                    HEARTBEAT_PATH,
                    content=original_body,
                    headers=original_headers,
                )
                stale = await master.post(
                    HEARTBEAT_PATH,
                    content=original_body,
                    headers=_signed_heartbeat_headers(
                        body=original_body,
                        node_id=node_id,
                        token=token,
                        nonce=secrets.token_hex(16),
                        timestamp=str(int(time.time()) - 3_600),
                    ),
                )
                invalid_token = await master.post(
                    HEARTBEAT_PATH,
                    content=original_body,
                    headers=_signed_heartbeat_headers(
                        body=original_body,
                        node_id=node_id,
                        token=wrong_token,
                        nonce=secrets.token_hex(16),
                    ),
                )
                assert (replayed.status_code, replayed.json()["code"]) == (
                    409,
                    "NODE_NONCE_REPLAYED",
                )
                assert (stale.status_code, stale.json()["code"]) == (
                    401,
                    "NODE_TIMESTAMP_INVALID",
                )
                assert (invalid_token.status_code, invalid_token.json()["code"]) == (
                    401,
                    "NODE_SIGNATURE_INVALID",
                )
                assert await _master_state(master, master_headers, node_id) == (
                    initial_node,
                    initial_assets,
                )

                await _wait_for_next_heartbeat(first_accepted_at)
                inventory_a = build_inventory(
                    node_id=node_id,
                    node_name="Integration Node",
                    version=node_settings.node_version,
                    hosts=[host_a],
                )
                await sync.master_client.heartbeat(inventory_a)
                retired_at = time.monotonic()
                retired_node, retired_assets = await _master_state(
                    master,
                    master_headers,
                    node_id,
                )
                _assert_complete_assets(
                    retired_assets,
                    node_id=node_id,
                    host_a=host_a,
                    host_b=host_b,
                    b_lifecycle="retired",
                )

                disabled = await master.patch(
                    f"/api/v1/nodes/{node_id}/status",
                    headers=master_headers,
                    json={"management_status": "disabled", "reason": "integration"},
                )
                assert disabled.status_code == 200, disabled.text
                assert disabled.json()["management_status"] == "disabled"
                disabled_state = await _master_state(master, master_headers, node_id)

                with pytest.raises(AppError) as disabled_error:
                    await sync.sync_now()
                assert disabled_error.value.code == "NODE_DISABLED"
                assert disabled_error.value.status_code == 403
                _assert_sync_status(sync, "disabled")
                local_disabled = await node.get(
                    "/api/v1/master-settings",
                    headers=node_headers,
                )
                assert local_disabled.json()["runtime_status"] == "disabled"
                assert await _master_state(master, master_headers, node_id) == disabled_state

                enabled = await master.patch(
                    f"/api/v1/nodes/{node_id}/status",
                    headers=master_headers,
                    json={"management_status": "active"},
                )
                assert enabled.status_code == 200, enabled.text
                assert enabled.json()["management_status"] == "active"

                await _wait_for_next_heartbeat(retired_at)
                await sync.sync_now()
                _assert_sync_status(sync, "online")
                local_online = await node.get(
                    "/api/v1/master-settings",
                    headers=node_headers,
                )
                assert local_online.json()["runtime_status"] == "online"
                recovered_node, recovered_assets = await _master_state(
                    master,
                    master_headers,
                    node_id,
                )
                assert recovered_node["management_status"] == "active"
                assert recovered_node["connectivity_status"] == "online"
                assert recovered_node["last_heartbeat_at"] != retired_node[
                    "last_heartbeat_at"
                ]
                _assert_complete_assets(
                    recovered_assets,
                    node_id=node_id,
                    host_a=host_a,
                    host_b=host_b,
                    b_lifecycle="active",
                )
