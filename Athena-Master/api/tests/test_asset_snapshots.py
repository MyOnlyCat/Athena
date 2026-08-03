import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncByteStream, AsyncClient
from sqlalchemy import insert, text

from app.models.asset import HostAsset
from app.models.registration import AccessNode
from tests.test_heartbeats import (
    HEARTBEAT_PATH,
    NODE_ID,
    approve_node,
    signed_headers,
)

HOST_ID = "019fae08-0ab1-7da1-9d22-612a0c5bb9ed"


class PausedRequestBody(AsyncByteStream):
    def __init__(self, body: bytes, first_chunk_sent: asyncio.Event, resume: asyncio.Event) -> None:
        self.body = body
        self.first_chunk_sent = first_chunk_sent
        self.resume = resume

    async def __aiter__(self) -> AsyncIterator[bytes]:
        midpoint = len(self.body) // 2
        yield self.body[:midpoint]
        self.first_chunk_sent.set()
        await self.resume.wait()
        yield self.body[midpoint:]


def heartbeat_with_hosts(hosts: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "protocol_version": "v1",
            "node": {
                "id": NODE_ID,
                "name": "上海接入节点",
                "version": "0.2.0",
                "hostname": "athena-node-01",
                "reported_at": "2026-08-01T08:00:00Z",
            },
            "hosts": hosts,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def reported_host(**overrides: object) -> dict[str, object]:
    host: dict[str, object] = {
        "id": HOST_ID,
        "name": "web-01",
        "address": "10.0.0.10",
        "port": 22,
        "username": "root",
        "tags": ["production", "上海"],
        "is_local": True,
        "last_test_status": "failed",
        "last_test_code": "SSH_TIMEOUT",
        "last_tested_at": "2026-08-01T07:59:00Z",
    }
    host.update(overrides)
    return host


def reported_hosts(
    count: int,
    *,
    name_prefix: str,
    address_suffix: int,
) -> list[dict[str, object]]:
    return [
        reported_host(
            id=str(UUID(int=index + 1)),
            name=f"{name_prefix}-{index:03d}",
            address=f"10.{index // 256}.{index % 256}.{address_suffix}",
            is_local=index == 0,
        )
        for index in range(count)
    ]


async def allow_next_heartbeat(app: FastAPI) -> None:
    async with app.state.session_factory() as session:
        await session.execute(
            text(
                "UPDATE access_nodes "
                "SET last_heartbeat_at = datetime('now', '-11 seconds') "
                "WHERE node_id = :node_id"
            ),
            {"node_id": NODE_ID},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_complete_heartbeat_snapshot_is_visible_through_admin_asset_api(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)
    body = heartbeat_with_hosts([reported_host()])

    heartbeat = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )
    assets = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
    )

    assert heartbeat.status_code == 200
    assert assets.status_code == 200
    assert assets.json() == {
        "items": [
            {
                "node_id": NODE_ID,
                "host_id": HOST_ID,
                "name": "web-01",
                "address": "10.0.0.10",
                "port": 22,
                "username": "root",
                "tags": ["production", "上海"],
                "is_local": True,
                "last_test_status": "failed",
                "last_test_code": "SSH_TIMEOUT",
                "last_tested_at": "2026-08-01T07:59:00Z",
                "lifecycle_status": "active",
                "retired_at": None,
                "source_node_connectivity_status": "online",
            }
        ],
        "page": 1,
        "page_size": 20,
        "total": 1,
    }


@pytest.mark.asyncio
async def test_missing_asset_is_retired_and_same_identity_is_restored(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    admin_headers = await approve_node(client)
    initial = heartbeat_with_hosts([reported_host()])
    assert (
        await client.post(
            HEARTBEAT_PATH,
            content=initial,
            headers=signed_headers(body=initial),
        )
    ).status_code == 200

    await allow_next_heartbeat(app)
    missing = heartbeat_with_hosts([])
    assert (
        await client.post(
            HEARTBEAT_PATH,
            content=missing,
            headers=signed_headers(
                body=missing,
                nonce="11111111111111111111111111111111",
            ),
        )
    ).status_code == 200
    retired = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={"lifecycle_status": "retired"},
    )
    assert retired.json()["total"] == 1
    assert retired.json()["items"][0]["retired_at"].endswith("Z")

    await allow_next_heartbeat(app)
    restored_body = heartbeat_with_hosts([reported_host(address="10.0.0.11")])
    assert (
        await client.post(
            HEARTBEAT_PATH,
            content=restored_body,
            headers=signed_headers(
                body=restored_body,
                nonce="22222222222222222222222222222222",
            ),
        )
    ).status_code == 200
    restored = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={"lifecycle_status": "active"},
    )
    assert restored.json()["total"] == 1
    assert restored.json()["items"][0]["address"] == "10.0.0.11"
    assert restored.json()["items"][0]["retired_at"] is None


@pytest.mark.asyncio
async def test_heartbeat_rejects_body_larger_than_five_mib(
    client: AsyncClient,
) -> None:
    await approve_node(client)
    oversized_body = b"{" + b" " * (5 * 1024 * 1024)

    response = await client.post(
        HEARTBEAT_PATH,
        content=oversized_body,
        headers=signed_headers(body=oversized_body),
    )

    assert response.status_code == 413
    assert response.json()["code"] == "NODE_PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_invalid_host_rolls_back_the_entire_snapshot(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    admin_headers = await approve_node(client)
    second_host_id = "019fae08-0ab1-7da1-9d22-612a0c5bb9ee"
    initial = heartbeat_with_hosts(
        [
            reported_host(),
            reported_host(
                id=second_host_id,
                name="db-01",
                address="10.0.0.20",
                tags=["database"],
            ),
        ]
    )
    assert (
        await client.post(
            HEARTBEAT_PATH,
            content=initial,
            headers=signed_headers(body=initial),
        )
    ).status_code == 200
    await allow_next_heartbeat(app)
    before_node = (
        await client.get("/api/v1/nodes", headers=admin_headers)
    ).json()["items"][0]

    invalid = heartbeat_with_hosts(
        [
            reported_host(address="10.0.0.99"),
            reported_host(
                id="019fae08-0ab1-7da1-9d22-612a0c5bb9ef",
                name="invalid-port",
                address="10.0.0.30",
                port=0,
            ),
        ]
    )
    rejected = await client.post(
        HEARTBEAT_PATH,
        content=invalid,
        headers=signed_headers(
            body=invalid,
            nonce="33333333333333333333333333333333",
        ),
    )
    after_assets = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
    )
    after_node = (
        await client.get("/api/v1/nodes", headers=admin_headers)
    ).json()["items"][0]

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "NODE_PAYLOAD_INVALID"
    assert after_assets.json()["total"] == 2
    assert {item["address"] for item in after_assets.json()["items"]} == {
        "10.0.0.10",
        "10.0.0.20",
    }
    assert all(
        item["lifecycle_status"] == "active"
        for item in after_assets.json()["items"]
    )
    assert after_node["last_heartbeat_at"] == before_node["last_heartbeat_at"]


@pytest.mark.asyncio
async def test_asset_api_filters_by_lifecycle_search_tag_and_detection_status(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)
    body = heartbeat_with_hosts(
        [
            reported_host(),
            reported_host(
                id="019fae08-0ab1-7da1-9d22-612a0c5bb9ee",
                name="db-01",
                address="10.0.0.20",
                tags=["database"],
                last_test_status="success",
                last_test_code="SSH_CONNECTED",
            ),
            reported_host(
                id="019fae08-0ab1-7da1-9d22-612a0c5bb9ef",
                name="untested-01",
                address="10.0.0.30",
                tags=["new"],
                last_test_status=None,
                last_test_code=None,
                last_tested_at=None,
            ),
        ]
    )
    assert (
        await client.post(
            HEARTBEAT_PATH,
            content=body,
            headers=signed_headers(body=body),
        )
    ).status_code == 200

    filtered = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={
            "page": 1,
            "page_size": 1,
            "search": "web",
            "lifecycle_status": "active",
            "detection_status": "failed",
            "tag": "production",
        },
    )

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["host_id"] == HOST_ID

    untested = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={"detection_status": "untested"},
    )
    assert untested.status_code == 200
    assert untested.json()["total"] == 1
    assert untested.json()["items"][0]["name"] == "untested-01"


@pytest.mark.asyncio
async def test_snapshot_accepts_five_hundred_hosts_and_rejects_more_atomically(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    admin_headers = await approve_node(client)
    hosts = reported_hosts(500, name_prefix="host", address_suffix=1)
    maximum = heartbeat_with_hosts(hosts)
    accepted = await client.post(
        HEARTBEAT_PATH,
        content=maximum,
        headers=signed_headers(body=maximum),
    )
    assert accepted.status_code == 200

    await allow_next_heartbeat(app)
    replacement = [
        reported_host(
            id=str(host["id"]),
            name=str(host["name"]),
            address=f"172.16.{index // 256}.{index % 256}",
            is_local=index == 0,
        )
        for index, host in enumerate(hosts[:250])
    ] + [
        reported_host(
            id=str(UUID(int=1001 + index)),
            name=f"replacement-{index:03d}",
            address=f"172.17.{index // 256}.{index % 256}",
            is_local=False,
        )
        for index in range(250)
    ]
    replacement_body = heartbeat_with_hosts(replacement)
    replaced = await client.post(
        HEARTBEAT_PATH,
        content=replacement_body,
        headers=signed_headers(
            body=replacement_body,
            nonce="44444444444444444444444444444444",
        ),
    )
    active = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={"lifecycle_status": "active", "page_size": 100},
    )
    retired = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={"lifecycle_status": "retired", "page_size": 100},
    )
    assert replaced.status_code == 200
    assert active.json()["total"] == 500
    assert retired.json()["total"] == 250

    await allow_next_heartbeat(app)
    too_many = heartbeat_with_hosts(
        [
            *replacement,
            reported_host(
                id=str(UUID(int=2001)),
                name="host-500",
                address="10.1.244.1",
                is_local=False,
            ),
        ]
    )
    rejected = await client.post(
        HEARTBEAT_PATH,
        content=too_many,
        headers=signed_headers(
            body=too_many,
            nonce="55555555555555555555555555555555",
        ),
    )
    assets = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={"lifecycle_status": "active", "page_size": 100},
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "NODE_PAYLOAD_INVALID"
    assert assets.json()["total"] == 500


@pytest.mark.asyncio
async def test_large_snapshot_does_not_hold_a_transaction_while_body_is_streaming(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)
    body = heartbeat_with_hosts(
        reported_hosts(500, name_prefix="streamed", address_suffix=2)
    )
    first_chunk_sent = asyncio.Event()
    resume = asyncio.Event()
    headers = signed_headers(body=body)
    headers["Content-Length"] = str(len(body))
    heartbeat_task = asyncio.create_task(
        client.post(
            HEARTBEAT_PATH,
            content=PausedRequestBody(body, first_chunk_sent, resume),
            headers=headers,
        )
    )
    await asyncio.wait_for(first_chunk_sent.wait(), timeout=1)

    administrator = await client.post(
        "/api/v1/administrators",
        headers=admin_headers,
        json={
            "username": "snapshot-reviewer",
            "password": "SnapshotReviewer123",
        },
    )
    resume.set()
    heartbeat = await heartbeat_task
    assets = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
        params={"lifecycle_status": "active", "page_size": 100},
    )

    assert administrator.status_code == 201
    assert heartbeat.status_code == 200
    assert assets.json()["total"] == 500


@pytest.mark.asyncio
async def test_global_active_asset_limit_rejects_snapshot_without_state_change(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    admin_headers = await approve_node(client)
    other_node_id = "019d3a7e-7c42-7000-8000-000000000008"
    async with app.state.session_factory() as session:
        session.add(
            AccessNode(
                node_id=other_node_id,
                reported_name="容量测试节点",
                hostname="capacity-node",
                software_version="0.2.0",
                management_status="active",
                encrypted_token="not-used-by-this-test",
                approved_at=datetime.now(UTC),
            )
        )
        await session.flush()
        await session.execute(
            insert(HostAsset),
            [
                {
                    "node_id": other_node_id,
                    "host_id": f"{index:036d}",
                    "name": f"existing-{index}",
                    "address": f"192.0.{index // 256}.{index % 256}",
                    "port": 22,
                    "username": "root",
                    "tags": [],
                    "is_local": False,
                    "last_test_status": None,
                    "last_test_code": None,
                    "last_tested_at": None,
                    "retired_at": None,
                }
                for index in range(10_000)
            ],
        )
        await session.commit()

    body = heartbeat_with_hosts([reported_host()])
    rejected = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )
    assets = await client.get(
        f"/api/v1/nodes/{NODE_ID}/assets",
        headers=admin_headers,
    )
    node = (await client.get("/api/v1/nodes", headers=admin_headers)).json()["items"][0]

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "ASSET_CAPACITY_EXCEEDED"
    assert assets.json()["total"] == 0
    assert node["last_heartbeat_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_field",
    [
        {"port": "22"},
        {"is_local": 1},
        {"last_tested_at": "2026-08-01T08:00:00"},
    ],
)
async def test_snapshot_strictly_rejects_coerced_host_field_types(
    client: AsyncClient,
    invalid_field: dict[str, object],
) -> None:
    await approve_node(client)
    body = heartbeat_with_hosts([reported_host(**invalid_field)])

    rejected = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "NODE_PAYLOAD_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hosts",
    [
        [reported_host(), reported_host(address="10.0.0.11")],
        [reported_host(last_test_message="SSH 连接失败")],
        [reported_host(last_test_status="unknown")],
        [reported_host(last_test_status="success", last_test_code="SSH_TIMEOUT")],
        [reported_host(tags=["production", "production"])],
    ],
)
async def test_snapshot_rejects_duplicate_ids_unknown_fields_and_invalid_values(
    client: AsyncClient,
    hosts: list[dict[str, object]],
) -> None:
    await approve_node(client)
    body = heartbeat_with_hosts(hosts)

    rejected = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "NODE_PAYLOAD_INVALID"
