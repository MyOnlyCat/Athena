from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.models.asset import HostAsset
from app.models.registration import AccessNode, RegistrationApplication
from app.services.node_status import connectivity_status
from tests.test_heartbeats import login_headers

ONLINE_NODE_ID = "019d3a7e-7c42-7000-8000-000000000010"
STALE_NODE_ID = "019d3a7e-7c42-7000-8000-000000000011"
OFFLINE_NODE_ID = "019d3a7e-7c42-7000-8000-000000000012"


def access_node(
    node_id: str,
    *,
    name: str,
    management_status: str,
    last_heartbeat_at: datetime,
) -> AccessNode:
    return AccessNode(
        node_id=node_id,
        reported_name=name,
        hostname=f"{name}.example.test",
        software_version="0.2.0",
        management_status=management_status,
        encrypted_token=f"encrypted-{node_id}",
        last_heartbeat_at=last_heartbeat_at,
    )


def application(node_id: str, *, status: str, now: datetime) -> RegistrationApplication:
    return RegistrationApplication(
        node_id=node_id,
        reported_name=f"申请-{node_id[-2:]}",
        hostname=f"application-{node_id[-2:]}",
        software_version="0.2.0",
        raw_body=b"{}",
        request_path="/api/node/v1/registration-applications",
        auth_timestamp=str(int(now.timestamp())),
        auth_nonce=node_id.replace("-", "")[-32:],
        auth_signature="a" * 64,
        status=status,
        received_at=now,
        status_changed_at=now,
    )


def host_asset(
    node_id: str,
    host_id: str,
    *,
    name: str,
    test_status: str,
    retired_at: datetime | None = None,
) -> HostAsset:
    return HostAsset(
        node_id=node_id,
        host_id=host_id,
        name=name,
        address="10.0.0.10",
        port=22,
        username="root",
        tags=[],
        is_local=False,
        last_test_status=test_status,
        last_test_code="SSH_TIMEOUT" if test_status == "failed" else "SSH_CONNECTED",
        last_tested_at=datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
        retired_at=retired_at,
    )


@pytest.mark.asyncio
async def test_overview_aggregates_node_and_active_asset_health(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    now = datetime.now(UTC)
    async with app.state.session_factory() as session:
        session.add_all(
            [
                access_node(
                    ONLINE_NODE_ID,
                    name="online-node",
                    management_status="active",
                    last_heartbeat_at=now - timedelta(seconds=30),
                ),
                access_node(
                    STALE_NODE_ID,
                    name="stale-node",
                    management_status="active",
                    last_heartbeat_at=now - timedelta(seconds=180),
                ),
                access_node(
                    OFFLINE_NODE_ID,
                    name="offline-node",
                    management_status="disabled",
                    last_heartbeat_at=now - timedelta(seconds=301),
                ),
                application(
                    "019d3a7e-7c42-7000-8000-000000000013",
                    status="pending",
                    now=now,
                ),
                application(
                    "019d3a7e-7c42-7000-8000-000000000014",
                    status="rejected",
                    now=now,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                host_asset(
                    ONLINE_NODE_ID,
                    "019fae08-0ab1-7da1-9d22-612a0c5bb901",
                    name="online-failed",
                    test_status="failed",
                ),
                host_asset(
                    STALE_NODE_ID,
                    "019fae08-0ab1-7da1-9d22-612a0c5bb902",
                    name="stale-failed",
                    test_status="failed",
                ),
                host_asset(
                    OFFLINE_NODE_ID,
                    "019fae08-0ab1-7da1-9d22-612a0c5bb903",
                    name="offline-success",
                    test_status="success",
                ),
                host_asset(
                    ONLINE_NODE_ID,
                    "019fae08-0ab1-7da1-9d22-612a0c5bb904",
                    name="retired-failed",
                    test_status="failed",
                    retired_at=now,
                ),
            ]
        )
        await session.commit()

    response = await client.get(
        "/api/v1/overview",
        headers=await login_headers(client),
    )

    assert response.status_code == 200
    assert response.json() == {
        "nodes": {
            "total": 5,
            "pending": 1,
            "active": 2,
            "disabled": 1,
            "rejected": 1,
            "online": 1,
            "stale": 1,
            "offline": 1,
        },
        "assets": {
            "active": 3,
            "abnormal": 1,
            "unknown": 1,
        },
    }


@pytest.mark.asyncio
async def test_asset_api_exposes_source_node_connectivity_and_keeps_last_test_details(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    now = datetime.now(UTC)
    async with app.state.session_factory() as session:
        session.add_all(
            [
                access_node(
                    STALE_NODE_ID,
                    name="stale-node",
                    management_status="active",
                    last_heartbeat_at=now - timedelta(seconds=180),
                ),
                access_node(
                    OFFLINE_NODE_ID,
                    name="offline-node",
                    management_status="active",
                    last_heartbeat_at=now - timedelta(seconds=301),
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                host_asset(
                    STALE_NODE_ID,
                    "019fae08-0ab1-7da1-9d22-612a0c5bb911",
                    name="stale-failed",
                    test_status="failed",
                ),
                host_asset(
                    OFFLINE_NODE_ID,
                    "019fae08-0ab1-7da1-9d22-612a0c5bb912",
                    name="offline-success",
                    test_status="success",
                ),
            ]
        )
        await session.commit()

    headers = await login_headers(client)
    stale = await client.get(
        f"/api/v1/nodes/{STALE_NODE_ID}/assets",
        headers=headers,
    )
    offline = await client.get(
        f"/api/v1/nodes/{OFFLINE_NODE_ID}/assets",
        headers=headers,
    )

    assert stale.status_code == 200
    assert stale.json()["items"][0]["source_node_connectivity_status"] == "stale"
    assert stale.json()["items"][0]["last_test_status"] == "failed"
    assert stale.json()["items"][0]["last_test_code"] == "SSH_TIMEOUT"
    assert offline.status_code == 200
    assert offline.json()["items"][0]["source_node_connectivity_status"] == "offline"
    assert offline.json()["items"][0]["last_test_status"] == "success"
    assert offline.json()["items"][0]["last_test_code"] == "SSH_CONNECTED"


def test_connectivity_boundaries_are_stable() -> None:
    now = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)

    assert connectivity_status(now - timedelta(seconds=119), now) == "online"
    assert connectivity_status(now - timedelta(seconds=120), now) == "stale"
    assert connectivity_status(now - timedelta(seconds=300), now) == "stale"
    assert connectivity_status(now - timedelta(seconds=301), now) == "offline"
