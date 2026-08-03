import json

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.models.registration import AccessNode
from app.services.crypto import node_token_fingerprint
from tests.test_asset_snapshots import heartbeat_with_hosts, reported_host
from tests.test_heartbeats import (
    HEARTBEAT_PATH,
    NODE_ID,
    approve_node,
    signed_headers,
)
from tests.test_registration_applications import signed_registration


async def login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassword123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def audit_page(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, object]:
    response = await client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"page": page, "page_size": page_size},
    )
    assert response.status_code == 200
    return dict(response.json())


@pytest.mark.asyncio
async def test_login_success_and_failure_are_audited_without_account_disclosure(
    client: AsyncClient,
) -> None:
    wrong_existing = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    wrong_unknown = await client.post(
        "/api/v1/auth/login",
        json={"username": "missing-admin", "password": "wrong-password"},
    )

    assert wrong_existing.status_code == wrong_unknown.status_code == 401
    assert wrong_existing.json() == wrong_unknown.json() == {
        "code": "INVALID_CREDENTIALS",
        "message": "用户名或密码错误",
    }

    headers = await login_headers(client)
    first_page = await audit_page(client, headers, page=1, page_size=2)
    second_page = await audit_page(client, headers, page=2, page_size=2)

    assert first_page["total"] == 3
    assert first_page["page"] == 1
    assert first_page["page_size"] == 2
    assert len(first_page["items"]) == 2  # type: ignore[arg-type]
    assert len(second_page["items"]) == 1  # type: ignore[arg-type]

    events = [*first_page["items"], *second_page["items"]]  # type: ignore[misc]
    assert {event["action"] for event in events} == {"auth.login"}
    assert [event["result"] for event in events].count("success") == 1
    assert [event["result"] for event in events].count("failure") == 2
    assert {
        event["target_id"] for event in events if event["result"] == "failure"
    } == {"admin", "missing-admin"}
    successful = next(event for event in events if event["result"] == "success")
    assert successful["actor_id"] is not None
    assert successful["actor_username"] == "admin"
    for event in events:
        assert event["created_at"].endswith("Z")
        assert event["source_ip"] == "127.0.0.1"

    unauthenticated = await client.get("/api/v1/audit-logs")
    read_only = await client.post("/api/v1/audit-logs", headers=headers, json={})
    assert unauthenticated.status_code == 401
    assert read_only.status_code == 405


@pytest.mark.asyncio
async def test_administrator_actions_record_success_failure_and_never_passwords(
    client: AsyncClient,
) -> None:
    headers = await login_headers(client)
    current = (await client.get("/api/v1/auth/me", headers=headers)).json()

    created = await client.post(
        "/api/v1/administrators",
        headers=headers,
        json={"username": "operator", "password": "OperatorPassword123"},
    )
    operator_id = created.json()["id"]
    duplicate = await client.post(
        "/api/v1/administrators",
        headers=headers,
        json={"username": "OPERATOR", "password": "AnotherPassword456"},
    )
    self_disable = await client.patch(
        f"/api/v1/administrators/{current['id']}/status",
        headers=headers,
        json={"is_active": False},
    )
    reset = await client.post(
        f"/api/v1/administrators/{operator_id}/reset-password",
        headers=headers,
        json={"password": "ChangedPassword456"},
    )
    disabled = await client.patch(
        f"/api/v1/administrators/{operator_id}/status",
        headers=headers,
        json={"is_active": False},
    )
    enabled = await client.patch(
        f"/api/v1/administrators/{operator_id}/status",
        headers=headers,
        json={"is_active": True},
    )

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert self_disable.status_code == 409
    assert reset.status_code == 204
    assert disabled.status_code == enabled.status_code == 200

    page = await audit_page(client, headers)
    events = page["items"]
    action_results = {(event["action"], event["result"]) for event in events}  # type: ignore[union-attr]
    assert {
        ("administrator.create", "success"),
        ("administrator.create", "failure"),
        ("administrator.disable", "success"),
        ("administrator.disable", "failure"),
        ("administrator.enable", "success"),
        ("administrator.password_reset", "success"),
    }.issubset(action_results)
    assert all(
        event["actor_username"] == "admin"
        for event in events  # type: ignore[union-attr]
        if event["action"].startswith("administrator.")
    )
    serialized = json.dumps(page, ensure_ascii=False)
    for password in (
        "OperatorPassword123",
        "AnotherPassword456",
        "ChangedPassword456",
    ):
        assert password not in serialized


@pytest.mark.asyncio
async def test_registration_and_node_management_actions_are_audited_without_tokens(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = "registration-secret-token-value-123"
    body, node_headers = signed_registration(token)
    submitted = await client.post(
        "/api/node/v1/registration-applications",
        content=body,
        headers=node_headers,
    )
    assert submitted.status_code == 202

    headers = await login_headers(client)
    applications = await client.get("/api/v1/registration-applications", headers=headers)
    application_id = applications.json()["items"][0]["id"]
    wrong_token = "wrong-registration-token-value-123"
    wrong_approval = await client.post(
        f"/api/v1/registration-applications/{application_id}/approve",
        headers=headers,
        json={"token": wrong_token},
    )
    approved = await client.post(
        f"/api/v1/registration-applications/{application_id}/approve",
        headers=headers,
        json={"token": token},
    )
    assert wrong_approval.status_code == 401
    assert approved.status_code == 200

    rejected_token = "rejected-registration-token-value-123"
    rejected_node_id = "018f47a2-4b5c-7def-8123-456789abcdee"
    rejected_body, rejected_headers = signed_registration(
        rejected_token,
        node_id=rejected_node_id,
        nonce="11111111111111111111111111111111",
    )
    submitted_for_rejection = await client.post(
        "/api/node/v1/registration-applications",
        content=rejected_body,
        headers=rejected_headers,
    )
    assert submitted_for_rejection.status_code == 202
    applications = await client.get("/api/v1/registration-applications", headers=headers)
    rejected_application_id = next(
        item["id"]
        for item in applications.json()["items"]
        if item["node_id"] == rejected_node_id
    )
    rejected = await client.post(
        f"/api/v1/registration-applications/{rejected_application_id}/reject",
        headers=headers,
        json={"reason": "来源未确认"},
    )
    restored = await client.post(
        f"/api/v1/registration-applications/{rejected_application_id}/restore",
        headers=headers,
    )
    assert rejected.status_code == restored.status_code == 200

    node_id = node_headers["X-Node-Id"]
    updated = await client.patch(
        f"/api/v1/nodes/{node_id}/management-info",
        headers=headers,
        json={
            "display_name": "审计节点",
            "notes": "人工维护",
            "management_tags": ["生产"],
        },
    )
    disabled = await client.patch(
        f"/api/v1/nodes/{node_id}/status",
        headers=headers,
        json={"management_status": "disabled", "reason": "维护"},
    )
    enabled = await client.patch(
        f"/api/v1/nodes/{node_id}/status",
        headers=headers,
        json={"management_status": "active"},
    )
    unchanged = await client.post(
        f"/api/v1/nodes/{node_id}/token",
        headers=headers,
        json={"token": token},
    )
    replacement_token = "replacement-registration-token-value-123"
    rotated = await client.post(
        f"/api/v1/nodes/{node_id}/token",
        headers=headers,
        json={"token": replacement_token},
    )
    assert updated.status_code == disabled.status_code == enabled.status_code == 200
    assert unchanged.status_code == 409
    assert rotated.status_code == 200

    page = await audit_page(client, headers)
    events = page["items"]
    action_results = {(event["action"], event["result"]) for event in events}  # type: ignore[union-attr]
    assert {
        ("registration.approve", "success"),
        ("registration.approve", "failure"),
        ("registration.reject", "success"),
        ("registration.restore", "success"),
        ("node.management_info.update", "success"),
        ("node.disable", "success"),
        ("node.enable", "success"),
        ("node.token.rotate", "success"),
        ("node.token.rotate", "failure"),
    }.issubset(action_results)
    serialized = json.dumps(page, ensure_ascii=False)
    async with app.state.session_factory() as session:
        stored_node = await session.get(AccessNode, node_id)
        assert stored_node is not None
        encrypted_token = stored_node.encrypted_token
    for secret in (token, wrong_token, rejected_token, replacement_token):
        assert secret not in serialized
        assert (
            node_token_fingerprint(app.state.settings.credential_key, secret)
            not in serialized
        )
    assert encrypted_token not in serialized
    assert all("details" not in event for event in events)  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_heartbeats_asset_sync_and_status_derivation_do_not_create_audit_noise(
    client: AsyncClient,
) -> None:
    headers = await approve_node(client)
    before = await audit_page(client, headers)

    body = heartbeat_with_hosts([reported_host()])
    heartbeat = await client.post(
        HEARTBEAT_PATH,
        content=body,
        headers=signed_headers(body=body),
    )
    await client.get("/api/v1/overview", headers=headers)
    await client.get("/api/v1/nodes", headers=headers)
    await client.get("/api/v1/registration-applications", headers=headers)
    after_success = await audit_page(client, headers)

    assert heartbeat.status_code == 200
    assert after_success["total"] == before["total"]

    disabled = await client.patch(
        f"/api/v1/nodes/{NODE_ID}/status",
        headers=headers,
        json={"management_status": "disabled"},
    )
    assert disabled.status_code == 200
    after_disable = await audit_page(client, headers)
    rejected_body = heartbeat_with_hosts([])
    rejected = await client.post(
        HEARTBEAT_PATH,
        content=rejected_body,
        headers=signed_headers(
            body=rejected_body,
            nonce="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        ),
    )
    after_rejection = await audit_page(client, headers)

    assert (rejected.status_code, rejected.json()["code"]) == (403, "NODE_DISABLED")
    assert after_rejection["total"] == after_disable["total"]
