from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.models.registration import AccessNode
from app.services.crypto import CredentialCipher, node_token_fingerprint
from tests.test_asset_snapshots import heartbeat_with_hosts, reported_host
from tests.test_heartbeats import (
    HEARTBEAT_PATH,
    approve_node,
    heartbeat_body,
    listed_node,
    signed_headers,
)


@pytest.mark.asyncio
async def test_managed_node_information_is_independent_from_heartbeat(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)

    updated = await client.patch(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/management-info",
        headers=admin_headers,
        json={
            "display_name": "上海生产节点",
            "notes": "由平台组维护",
            "management_tags": ["生产", "华东"],
        },
    )

    assert updated.status_code == 200
    assert updated.json()["display_name"] == "上海生产节点"
    assert updated.json()["effective_name"] == "上海生产节点"
    assert updated.json()["notes"] == "由平台组维护"
    assert updated.json()["management_tags"] == ["生产", "华东"]
    assert "token" not in updated.text.lower()

    body = heartbeat_body(reported_name="Node 新上报名")
    heartbeat = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )
    assert heartbeat.status_code == 200

    node = await listed_node(client, admin_headers)
    assert node["reported_name"] == "Node 新上报名"
    assert node["display_name"] == "上海生产节点"
    assert node["effective_name"] == "上海生产节点"
    assert node["notes"] == "由平台组维护"
    assert node["management_tags"] == ["生产", "华东"]


@pytest.mark.asyncio
async def test_disabling_rejects_heartbeat_and_reenabling_restores_it(
    client: AsyncClient,
) -> None:
    admin_headers = await approve_node(client)
    accepted_at = (await listed_node(client, admin_headers))["last_heartbeat_at"]

    disabled = await client.patch(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/status",
        headers=admin_headers,
        json={"management_status": "disabled", "reason": "计划维护"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["management_status"] == "disabled"
    assert disabled.json()["disable_reason"] == "计划维护"

    rejected_body = heartbeat_body(reported_name="不应写入")
    rejected = await client.post(
        HEARTBEAT_PATH,
        content=rejected_body,
        headers=signed_headers(
            body=rejected_body,
            nonce="99999999999999999999999999999999",
        ),
    )
    assert (rejected.status_code, rejected.json()["code"]) == (403, "NODE_DISABLED")
    unchanged = await listed_node(client, admin_headers)
    assert unchanged["last_heartbeat_at"] == accepted_at
    assert unchanged["reported_name"] == "注册时名称"

    enabled = await client.patch(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/status",
        headers=admin_headers,
        json={"management_status": "active"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["management_status"] == "active"
    assert enabled.json()["disable_reason"] is None

    recovery_body = heartbeat_body(reported_name="恢复后")
    recovered = await client.post(
        HEARTBEAT_PATH,
        content=recovery_body,
        headers=signed_headers(
            body=recovery_body,
            nonce="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
    )
    assert recovered.status_code == 200
    assert (await listed_node(client, admin_headers))["reported_name"] == "恢复后"


@pytest.mark.asyncio
async def test_disabling_retains_node_identity_and_host_assets(client: AsyncClient) -> None:
    admin_headers = await approve_node(client)
    body = heartbeat_with_hosts([reported_host()])
    accepted = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )
    assert accepted.status_code == 200

    disabled = await client.patch(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/status",
        headers=admin_headers,
        json={"management_status": "disabled"},
    )
    assets = await client.get(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/assets",
        headers=admin_headers,
    )

    assert disabled.status_code == 200
    assert disabled.json()["disable_reason"] is None
    assert (await listed_node(client, admin_headers))["management_status"] == "disabled"
    assert assets.status_code == 200
    assert assets.json()["total"] == 1
    assert assets.json()["items"][0]["name"] == "web-01"


def assert_no_secret_fields(payload: dict[str, Any]) -> None:
    assert not any("token" in key.lower() for key in payload)


@pytest.mark.asyncio
async def test_rotating_token_invalidates_the_old_token_without_disclosing_secrets(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    admin_headers = await approve_node(client)
    new_token = "replacement-node-token-value-123456789"

    rotated = await client.post(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/token",
        headers=admin_headers,
        json={"token": new_token},
    )

    assert rotated.status_code == 200
    assert_no_secret_fields(rotated.json())
    assert new_token not in rotated.text
    async with app.state.session_factory() as session:
        node = await session.get(AccessNode, "019d3a7e-7c42-7000-8000-000000000007")
        assert node is not None
        assert node.encrypted_token != new_token
        assert CredentialCipher(app.state.settings.credential_key).decrypt(
            node.encrypted_token
        ) == new_token

    body = heartbeat_body(reported_name="轮换后")
    old_token = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )
    assert (old_token.status_code, old_token.json()["code"]) == (
        401,
        "NODE_SIGNATURE_INVALID",
    )

    new_token_response = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(
            body=body,
            token=new_token,
            nonce="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        ),
    )
    assert new_token_response.status_code == 200


@pytest.mark.asyncio
async def test_rotating_token_rejects_a_token_owned_by_another_node(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    admin_headers = await approve_node(client)
    other_token = "other-node-token-value-12345678901234"
    cipher = CredentialCipher(app.state.settings.credential_key)
    async with app.state.session_factory() as session:
        session.add(
            AccessNode(
                node_id="019d3a7e-7c42-7000-8000-000000000008",
                reported_name="另一个节点",
                hostname="other-node",
                software_version="0.2.0",
                encrypted_token=cipher.encrypt(other_token),
                token_fingerprint=node_token_fingerprint(
                    app.state.settings.credential_key,
                    other_token,
                ),
            )
        )
        await session.commit()

    duplicate = await client.post(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/token",
        headers=admin_headers,
        json={"token": other_token},
    )

    assert (duplicate.status_code, duplicate.json()["code"]) == (
        409,
        "NODE_TOKEN_DUPLICATE",
    )
    assert other_token not in duplicate.text

    body = heartbeat_body(reported_name="仍使用旧 Token")
    unchanged = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )
    assert unchanged.status_code == 200


@pytest.mark.asyncio
async def test_rotating_token_rejects_the_current_token(client: AsyncClient) -> None:
    admin_headers = await approve_node(client)

    unchanged = await client.post(
        "/api/v1/nodes/019d3a7e-7c42-7000-8000-000000000007/token",
        headers=admin_headers,
        json={"token": "node-token-for-authenticated-heartbeat"},
    )

    assert (unchanged.status_code, unchanged.json()["code"]) == (
        409,
        "NODE_TOKEN_UNCHANGED",
    )
    assert "node-token-for-authenticated-heartbeat" not in unchanged.text
