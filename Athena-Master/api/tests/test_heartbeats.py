import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import Settings
from app.main import create_app
from app.schemas.heartbeat import HeartbeatNode

NODE_ID = "019d3a7e-7c42-7000-8000-000000000007"
NODE_TOKEN = "node-token-for-authenticated-heartbeat"
HEARTBEAT_PATH = "/api/node/v1/nodes/heartbeat"


def signed_headers(
    *,
    body: bytes,
    node_id: str = NODE_ID,
    token: str = NODE_TOKEN,
    timestamp: str | None = None,
    nonce: str = "0123456789abcdef0123456789abcdef",
    path: str = HEARTBEAT_PATH,
) -> dict[str, str]:
    timestamp = timestamp or str(int(datetime.now(UTC).timestamp()))
    canonical = "\n".join(
        (
            "POST",
            path,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        )
    )
    signature = hmac.new(
        token.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Node-Id": node_id,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


def heartbeat_body(
    *,
    protocol_version: str = "v1",
    reported_name: str = "上海接入节点",
    hostname: str = "athena-node-01",
    software_version: str = "0.2.0",
    reported_at: str = "2000-01-01T00:00:00Z",
) -> bytes:
    return json.dumps(
        {
            "protocol_version": protocol_version,
            "node": {
                "id": NODE_ID,
                "name": reported_name,
                "version": software_version,
                "hostname": hostname,
                "reported_at": reported_at,
            },
            "hosts": [],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


async def login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassword123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def approve_node(client: AsyncClient) -> dict[str, str]:
    registration_body = json.dumps(
        {
            "node_id": NODE_ID,
            "reported_name": "注册时名称",
            "hostname": "registration-host",
            "software_version": "0.1.0",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    registration = await client.post(
        "/api/node/v1/registration-applications",
        content=registration_body,
        headers=signed_headers(
            body=registration_body,
            path="/api/node/v1/registration-applications",
        ),
    )
    assert registration.status_code == 202

    admin_headers = await login_headers(client)
    applications = await client.get(
        "/api/v1/registration-applications",
        headers=admin_headers,
    )
    application_id = applications.json()["items"][0]["id"]
    approval = await client.post(
        f"/api/v1/registration-applications/{application_id}/approve",
        headers=admin_headers,
        json={"token": NODE_TOKEN},
    )
    assert approval.status_code == 200
    return admin_headers


async def listed_node(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> dict[str, Any]:
    response = await client.get("/api/v1/nodes", headers=admin_headers)
    assert response.status_code == 200
    return dict(response.json()["items"][0])


@pytest.mark.asyncio
async def test_pending_and_rejected_nodes_have_distinct_heartbeat_contracts(
    client: AsyncClient,
) -> None:
    registration_body = json.dumps(
        {
            "node_id": NODE_ID,
            "reported_name": "待审批节点",
            "hostname": "pending-node",
            "software_version": "0.1.0",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    submitted = await client.post(
        "/api/node/v1/registration-applications",
        content=registration_body,
        headers=signed_headers(
            body=registration_body,
            path="/api/node/v1/registration-applications",
        ),
    )
    heartbeat = heartbeat_body()
    pending = await client.post(
        HEARTBEAT_PATH,
        content=heartbeat,
        headers=signed_headers(
            body=heartbeat,
            nonce="10101010101010101010101010101010",
        ),
    )

    admin_headers = await login_headers(client)
    applications = await client.get(
        "/api/v1/registration-applications",
        headers=admin_headers,
    )
    application_id = applications.json()["items"][0]["id"]
    rejected_application = await client.post(
        f"/api/v1/registration-applications/{application_id}/reject",
        headers=admin_headers,
        json={},
    )
    rejected = await client.post(
        HEARTBEAT_PATH,
        content=heartbeat,
        headers=signed_headers(
            body=heartbeat,
            nonce="20202020202020202020202020202020",
        ),
    )
    final_applications = await client.get(
        "/api/v1/registration-applications",
        headers=admin_headers,
    )

    assert submitted.status_code == 202
    assert pending.status_code == 404
    assert pending.json() == {
        "code": "NODE_NOT_APPROVED",
        "message": "节点尚未批准",
    }
    assert rejected_application.status_code == 200
    assert rejected.status_code == 409
    assert rejected.json() == {
        "code": "REGISTRATION_REJECTED",
        "message": "接入申请已被拒绝，请联系管理员恢复后手动重试",
    }
    assert final_applications.json()["items"][0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_authenticated_heartbeat_updates_reported_node_state_from_raw_body(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)
    body = (
        b'{ "protocol_version" : "v1", "node" : {'
        b'"id":"019d3a7e-7c42-7000-8000-000000000007",'
        b'"name":"\\u4e0a\\u6d77\\u5fc3\\u8df3\\u8282\\u70b9",'
        b'"version":"0.2.0","hostname":"heartbeat-host",'
        b'"reported_at":"2000-01-01T00:00:00Z"},"hosts":[] }'
    )
    path_with_query = f"{HEARTBEAT_PATH}?source=contract"

    response = await client.post(
        path_with_query,
        content=body,
        headers=signed_headers(body=body, path=path_with_query),
    )

    assert response.status_code == 200
    assert response.json()["next_heartbeat_seconds"] == 60
    assert response.json()["accepted_at"].endswith("Z")
    node = await listed_node(client, admin_headers)
    assert node["reported_name"] == "上海心跳节点"
    assert node["hostname"] == "heartbeat-host"
    assert node["software_version"] == "0.2.0"
    assert node["management_status"] == "active"
    assert node["connectivity_status"] == "online"
    assert node["last_heartbeat_at"] != "2000-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_heartbeat_rejections_do_not_change_last_heartbeat(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)
    accepted_body = heartbeat_body(reported_name="已接受名称")
    accepted = await client.post(
        HEARTBEAT_PATH,
        content=accepted_body,
        headers=signed_headers(body=accepted_body),
    )
    assert accepted.status_code == 200
    accepted_at = (await listed_node(client, admin_headers))["last_heartbeat_at"]

    replayed = await client.post(
        HEARTBEAT_PATH,
        content=accepted_body,
        headers=signed_headers(body=accepted_body),
    )
    assert (replayed.status_code, replayed.json()["code"]) == (
        409,
        "NODE_NONCE_REPLAYED",
    )

    expired_body = heartbeat_body(reported_name="过期请求名称")
    expired = await client.post(
        HEARTBEAT_PATH,
        content=expired_body,
        headers=signed_headers(
            body=expired_body,
            timestamp=str(int((datetime.now(UTC) - timedelta(seconds=301)).timestamp())),
            nonce="11111111111111111111111111111111",
        ),
    )
    assert (expired.status_code, expired.json()["code"]) == (
        401,
        "NODE_TIMESTAMP_INVALID",
    )

    wrong_token_body = heartbeat_body(reported_name="错误 Token 名称")
    wrong_token = await client.post(
        HEARTBEAT_PATH,
        content=wrong_token_body,
        headers=signed_headers(
            body=wrong_token_body,
            token="wrong-token-with-at-least-32-characters",
            nonce="22222222222222222222222222222222",
        ),
    )
    assert (wrong_token.status_code, wrong_token.json()["code"]) == (
        401,
        "NODE_SIGNATURE_INVALID",
    )
    assert (await listed_node(client, admin_headers))["last_heartbeat_at"] == accepted_at
    assert (await listed_node(client, admin_headers))["reported_name"] == "已接受名称"


@pytest.mark.asyncio
async def test_heartbeat_rejects_reported_at_without_timezone(
    client: AsyncClient,
) -> None:
    await approve_node(client)
    body = heartbeat_body(reported_at="2026-08-03T10:30:00")

    response = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(
            body=body,
            nonce="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "NODE_PAYLOAD_INVALID",
        "message": "心跳负载无效",
    }


def test_heartbeat_reported_at_is_normalized_to_utc() -> None:
    node = HeartbeatNode.model_validate(
        {
            "id": NODE_ID,
            "name": "上海接入节点",
            "version": "0.2.0",
            "hostname": "athena-node-01",
            "reported_at": "2026-08-03T18:30:00+08:00",
        }
    )

    assert node.reported_at.isoformat() == "2026-08-03T10:30:00+00:00"


@pytest.mark.asyncio
async def test_heartbeat_rejects_unknown_node_bad_nonce_protocol_and_fast_repeat(
    client: AsyncClient,
) -> None:
    await approve_node(client)
    body = heartbeat_body()

    unknown = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(
            body=body,
            node_id="019d3a7e-7c42-7000-8000-000000000099",
        ),
    )
    assert (unknown.status_code, unknown.json()["code"]) == (404, "NODE_NOT_FOUND")

    bad_nonce = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body, nonce="NOT-A-VALID-NONCE"),
    )
    assert (bad_nonce.status_code, bad_nonce.json()["code"]) == (
        422,
        "NODE_AUTH_INVALID",
    )

    unsupported_body = heartbeat_body(protocol_version="v2")
    unsupported = await client.post(
        HEARTBEAT_PATH,
        content=unsupported_body,
        headers=signed_headers(
            body=unsupported_body,
            nonce="33333333333333333333333333333333",
        ),
    )
    assert (unsupported.status_code, unsupported.json()["code"]) == (
        426,
        "NODE_PROTOCOL_UNSUPPORTED",
    )
    assert unsupported.json()["message"] == "节点协议版本不受支持"
    unsupported_replay = await client.post(
        HEARTBEAT_PATH,
        content=unsupported_body,
        headers=signed_headers(
            body=unsupported_body,
            nonce="33333333333333333333333333333333",
        ),
    )
    assert (unsupported_replay.status_code, unsupported_replay.json()["code"]) == (
        409,
        "NODE_NONCE_REPLAYED",
    )

    first_body = heartbeat_body(reported_name="第一次")
    first = await client.post(
        HEARTBEAT_PATH,
        content=first_body,
        headers=signed_headers(
            body=first_body,
            nonce="44444444444444444444444444444444",
        ),
    )
    assert first.status_code == 200
    second_body = heartbeat_body(reported_name="过快请求")
    second = await client.post(
        HEARTBEAT_PATH,
        content=second_body,
        headers=signed_headers(
            body=second_body,
            nonce="55555555555555555555555555555555",
        ),
    )
    assert (second.status_code, second.json()["code"]) == (429, "NODE_RATE_LIMITED")
    second_replay = await client.post(
        HEARTBEAT_PATH,
        content=second_body,
        headers=signed_headers(
            body=second_body,
            nonce="55555555555555555555555555555555",
        ),
    )
    assert (second_replay.status_code, second_replay.json()["code"]) == (
        409,
        "NODE_NONCE_REPLAYED",
    )


@pytest.mark.asyncio
async def test_replay_protection_survives_master_restart(settings: Settings) -> None:
    body = heartbeat_body()
    headers = signed_headers(body=body)
    first_app = create_app(settings)
    async with first_app.router.lifespan_context(first_app):
        async with AsyncClient(
            transport=ASGITransport(app=first_app),
            base_url="http://test",
        ) as first_client:
            await approve_node(first_client)
            accepted = await first_client.post(
                HEARTBEAT_PATH,
                content=body,
                headers=headers,
            )
            assert accepted.status_code == 200

    restarted_app = create_app(settings)
    async with restarted_app.router.lifespan_context(restarted_app):
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app),
            base_url="http://test",
        ) as restarted_client:
            replayed = await restarted_client.post(
                HEARTBEAT_PATH,
                content=body,
                headers=headers,
            )
            assert (replayed.status_code, replayed.json()["code"]) == (
                409,
                "NODE_NONCE_REPLAYED",
            )


@pytest.mark.asyncio
async def test_node_api_limit_is_shared_across_status_and_heartbeat_routes(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)
    status_body = b"{}"
    status_path = "/api/node/v1/registration-applications/status"
    for index in range(19):
        response = await client.post(
            status_path,
            content=status_body,
            headers=signed_headers(
                body=status_body,
                nonce=f"{index + 100:032x}",
                path=status_path,
            ),
        )
        assert response.status_code == 200

    limited_body = heartbeat_body(reported_name="不应被接受")
    limited = await client.post(
        HEARTBEAT_PATH,
        content=limited_body,
        headers=signed_headers(
            body=limited_body,
            nonce="ffffffffffffffffffffffffffffffff",
        ),
    )
    assert (limited.status_code, limited.json()["code"]) == (429, "NODE_RATE_LIMITED")
    replayed = await client.post(
        HEARTBEAT_PATH,
        content=limited_body,
        headers=signed_headers(
            body=limited_body,
            nonce="ffffffffffffffffffffffffffffffff",
        ),
    )
    assert (replayed.status_code, replayed.json()["code"]) == (
        409,
        "NODE_NONCE_REPLAYED",
    )
    node = await listed_node(client, admin_headers)
    assert node["reported_name"] == "注册时名称"
    assert node["last_heartbeat_at"] is None


@pytest.mark.asyncio
async def test_node_list_paginates_filters_sorts_and_uses_master_receipt_time(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    admin_headers = await approve_node(client)
    now = datetime.now(UTC)
    async with app.state.session_factory() as session:
        await session.execute(
            text(
                "UPDATE access_nodes SET last_heartbeat_at = :last_heartbeat "
                "WHERE node_id = :node_id"
            ),
            {
                "last_heartbeat": now - timedelta(seconds=120),
                "node_id": NODE_ID,
            },
        )
        await session.commit()

    stale = await client.get(
        "/api/v1/nodes",
        params={
            "connectivity_status": "stale",
            "search": "注册时",
            "sort_by": "reported_name",
            "sort_order": "asc",
            "page": 1,
            "page_size": 1,
        },
        headers=admin_headers,
    )
    assert stale.status_code == 200
    assert stale.json()["total"] == 1
    assert stale.json()["items"][0]["connectivity_status"] == "stale"
    assert stale.json()["items"][0]["approved_at"].endswith("Z")
    assert stale.json()["items"][0]["last_heartbeat_at"].endswith("Z")

    async with app.state.session_factory() as session:
        await session.execute(
            text(
                "UPDATE access_nodes SET last_heartbeat_at = :last_heartbeat "
                "WHERE node_id = :node_id"
            ),
            {
                "last_heartbeat": now - timedelta(seconds=301),
                "node_id": NODE_ID,
            },
        )
        await session.commit()

    offline = await client.get(
        "/api/v1/nodes",
        params={"connectivity_status": "offline"},
        headers=admin_headers,
    )
    assert offline.status_code == 200
    assert offline.json()["total"] == 1
    assert offline.json()["items"][0]["connectivity_status"] == "offline"
