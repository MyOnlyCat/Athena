import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.services.crypto import CredentialCipher


async def login_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassword123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def signed_registration(
    token: str,
    *,
    node_id: str = "018f47a2-4b5c-7def-8123-456789abcdef",
    timestamp: str | None = None,
    nonce: str = "0123456789abcdef0123456789abcdef",
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "node_id": node_id,
            "reported_name": "上海接入节点",
            "hostname": "athena-node-01",
            "software_version": "0.1.0",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    effective_timestamp = timestamp or str(int(datetime.now(UTC).timestamp()))
    canonical = "\n".join(
        (
            "POST",
            "/api/node/v1/registration-applications",
            effective_timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        )
    )
    signature = hmac.new(
        token.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Node-Id": node_id,
        "X-Timestamp": effective_timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


def signed_status(token: str, node_id: str) -> tuple[bytes, dict[str, str]]:
    body = b"{}"
    timestamp = str(int(datetime.now(UTC).timestamp()))
    nonce = "abcdef0123456789abcdef0123456789"
    path = "/api/node/v1/registration-applications/status"
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
    return body, {
        "Content-Type": "application/json",
        "X-Node-Id": node_id,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }


@pytest.mark.asyncio
async def test_registration_is_stored_as_untrusted_and_approved_from_exact_bytes(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = "registration-secret-token-value-123"
    body, headers = signed_registration(token)

    submitted = await client.post(
        "/api/node/v1/registration-applications",
        content=body,
        headers=headers,
    )
    pending_status_body, pending_status_headers = signed_status(
        token,
        headers["X-Node-Id"],
    )
    pending_status = await client.post(
        "/api/node/v1/registration-applications/status",
        content=pending_status_body,
        headers=pending_status_headers,
    )
    pending_status_body, pending_status_headers = signed_status(
        token,
        headers["X-Node-Id"],
    )
    pending_status = await client.post(
        "/api/node/v1/registration-applications/status",
        content=pending_status_body,
        headers=pending_status_headers,
    )
    async with app.state.session_factory() as session:
        stored_application = (
            await session.execute(
                text(
                    "SELECT raw_body, auth_signature FROM registration_applications"
                )
            )
        ).one()
    admin_headers = await login_headers(client)
    listed = await client.get(
        "/api/v1/registration-applications?page=1&page_size=20",
        headers=admin_headers,
    )
    application_id = listed.json()["items"][0]["id"]
    wrong = await client.post(
        f"/api/v1/registration-applications/{application_id}/approve",
        headers=admin_headers,
        json={"token": "wrong-registration-token-value-123"},
    )
    still_pending = await client.get(
        "/api/v1/registration-applications?page=1&page_size=20",
        headers=admin_headers,
    )
    approved = await client.post(
        f"/api/v1/registration-applications/{application_id}/approve",
        headers=admin_headers,
        json={"token": token},
    )
    status_body, status_headers = signed_status(token, headers["X-Node-Id"])
    registration_status = await client.post(
        "/api/node/v1/registration-applications/status",
        content=status_body,
        headers=status_headers,
    )
    wrong_status_body, wrong_status_headers = signed_status(
        "wrong-registration-token-value-123",
        headers["X-Node-Id"],
    )
    wrong_registration_status = await client.post(
        "/api/node/v1/registration-applications/status",
        content=wrong_status_body,
        headers=wrong_status_headers,
    )
    wrong_status_body, wrong_status_headers = signed_status(
        "wrong-registration-token-value-123",
        headers["X-Node-Id"],
    )
    wrong_registration_status = await client.post(
        "/api/node/v1/registration-applications/status",
        content=wrong_status_body,
        headers=wrong_status_headers,
    )
    async with app.state.session_factory() as session:
        encrypted_token = (
            await session.execute(text("SELECT encrypted_token FROM access_nodes"))
        ).scalar_one()

    assert submitted.status_code == 202
    assert submitted.json()["status"] == "pending"
    assert pending_status.status_code == 200
    assert pending_status.json() == {"status": "pending"}
    assert token not in submitted.text
    assert stored_application.raw_body == body
    assert stored_application.auth_signature == headers["X-Signature"]
    assert listed.status_code == 200
    assert listed.json()["items"][0]["received_at"].endswith("Z")
    assert listed.json()["items"][0] == {
        "id": application_id,
        "node_id": "018f47a2-4b5c-7def-8123-456789abcdef",
        "reported_name": "上海接入节点",
        "hostname": "athena-node-01",
        "software_version": "0.1.0",
        "status": "pending",
        "identity_verified": False,
        "received_at": listed.json()["items"][0]["received_at"],
    }
    assert wrong.status_code == 401
    assert wrong.json() == {
        "code": "REGISTRATION_TOKEN_INVALID",
        "message": "Token 与注册申请不匹配",
    }
    assert still_pending.json()["items"][0]["status"] == "pending"
    assert approved.status_code == 200
    assert approved.json()["management_status"] == "active"
    assert approved.json()["node_id"] == headers["X-Node-Id"]
    assert approved.json()["approved_at"].endswith("Z")
    assert registration_status.status_code == 200
    assert registration_status.json() == {"status": "approved"}
    assert wrong_registration_status.status_code == 401
    assert wrong_registration_status.json()["code"] == "REGISTRATION_TOKEN_INVALID"
    assert wrong_registration_status.status_code == 401
    assert wrong_registration_status.json()["code"] == "REGISTRATION_TOKEN_INVALID"
    assert token not in approved.text
    assert encrypted_token != token
    assert (
        CredentialCipher(app.state.settings.credential_key).decrypt(encrypted_token)
        == token
    )


@pytest.mark.asyncio
async def test_registration_rejects_stale_timestamp_and_header_body_identity_mismatch(
    client: AsyncClient,
) -> None:
    stale_body, stale_headers = signed_registration(
        "registration-secret-token-value-123",
        timestamp="1780000000",
    )
    mismatch_body, mismatch_headers = signed_registration(
        "registration-secret-token-value-123",
    )
    mismatch_headers["X-Node-Id"] = "018f47a2-4b5c-7def-8123-456789abcdee"

    stale = await client.post(
        "/api/node/v1/registration-applications",
        content=stale_body,
        headers=stale_headers,
    )
    mismatch = await client.post(
        "/api/node/v1/registration-applications",
        content=mismatch_body,
        headers=mismatch_headers,
    )

    assert stale.status_code == 401
    assert stale.json()["code"] == "NODE_TIMESTAMP_INVALID"
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "REGISTRATION_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_approval_rechecks_the_stored_registration_time_window(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = "registration-secret-token-value-123"
    body, headers = signed_registration(token)
    submitted = await client.post(
        "/api/node/v1/registration-applications",
        content=body,
        headers=headers,
    )
    stale_received_at = datetime.fromtimestamp(
        int(headers["X-Timestamp"]) - 600,
        UTC,
    )
    async with app.state.session_factory() as session:
        application_id = (
            await session.execute(
                text("SELECT id FROM registration_applications")
            )
        ).scalar_one()
        await session.execute(
            text(
                "UPDATE registration_applications "
                "SET received_at = :received_at WHERE id = :application_id"
            ),
            {
                "received_at": stale_received_at.isoformat(sep=" "),
                "application_id": application_id,
            },
        )
        await session.commit()

    approval = await client.post(
        f"/api/v1/registration-applications/{application_id}/approve",
        headers=await login_headers(client),
        json={"token": token},
    )
    async with app.state.session_factory() as session:
        application_status = (
            await session.execute(
                text(
                    "SELECT status FROM registration_applications "
                    "WHERE id = :application_id"
                ),
                {"application_id": application_id},
            )
        ).scalar_one()
        access_node_count = (
            await session.execute(text("SELECT count(*) FROM access_nodes"))
        ).scalar_one()

    assert submitted.status_code == 202
    assert approval.status_code == 401
    assert approval.json()["code"] == "NODE_TIMESTAMP_INVALID"
    assert application_status == "pending"
    assert access_node_count == 0


@pytest.mark.asyncio
async def test_rejected_node_cannot_reapply_until_an_administrator_restores_it(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = "registration-secret-token-value-123"
    body, headers = signed_registration(token)
    assert (
        await client.post(
            "/api/node/v1/registration-applications",
            content=body,
            headers=headers,
        )
    ).status_code == 202
    admin_headers = await login_headers(client)
    listed = await client.get("/api/v1/registration-applications", headers=admin_headers)
    application_id = listed.json()["items"][0]["id"]

    rejected = await client.post(
        f"/api/v1/registration-applications/{application_id}/reject",
        headers=admin_headers,
        json={"reason": "来源尚未核实"},
    )
    status_body, status_headers = signed_status(token, headers["X-Node-Id"])
    node_status = await client.post(
        "/api/node/v1/registration-applications/status",
        content=status_body,
        headers=status_headers,
    )
    retry_body, retry_headers = signed_registration(
        token,
        nonce="11111111111111111111111111111111",
    )
    blocked_retry = await client.post(
        "/api/node/v1/registration-applications",
        content=retry_body,
        headers=retry_headers,
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejection_reason"] == "来源尚未核实"
    assert node_status.json() == {"status": "rejected"}
    assert blocked_retry.status_code == 409
    assert blocked_retry.json()["code"] == "REGISTRATION_REJECTED"

    restored = await client.post(
        f"/api/v1/registration-applications/{application_id}/restore",
        headers=admin_headers,
    )
    async with app.state.session_factory() as session:
        await session.execute(
            text(
                "UPDATE registration_applications SET received_at = :old "
                "WHERE id = :application_id"
            ),
            {
                "old": datetime.now(UTC) - timedelta(minutes=2),
                "application_id": application_id,
            },
        )
        await session.commit()
    accepted_retry = await client.post(
        "/api/node/v1/registration-applications",
        content=retry_body,
        headers=retry_headers,
    )

    assert restored.status_code == 200
    assert restored.json()["status"] == "restored"
    assert accepted_retry.status_code == 202


@pytest.mark.asyncio
async def test_pending_applications_expire_and_old_terminal_applications_are_cleaned(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = "registration-secret-token-value-123"
    body, headers = signed_registration(token)
    await client.post(
        "/api/node/v1/registration-applications",
        content=body,
        headers=headers,
    )
    async with app.state.session_factory() as session:
        application_id = (
            await session.execute(text("SELECT id FROM registration_applications"))
        ).scalar_one()
        await session.execute(
            text(
                "UPDATE registration_applications SET received_at = :old "
                "WHERE id = :application_id"
            ),
            {
                "old": datetime.now(UTC) - timedelta(days=8),
                "application_id": application_id,
            },
        )
        await session.commit()

    admin_headers = await login_headers(client)
    expired = await client.get("/api/v1/registration-applications", headers=admin_headers)
    approval = await client.post(
        f"/api/v1/registration-applications/{application_id}/approve",
        headers=admin_headers,
        json={"token": token},
    )
    assert expired.json()["items"][0]["status"] == "expired"
    assert approval.status_code == 409
    assert approval.json()["code"] == "REGISTRATION_EXPIRED"

    async with app.state.session_factory() as session:
        await session.execute(
            text(
                "UPDATE registration_applications SET status_changed_at = :old "
                "WHERE id = :application_id"
            ),
            {
                "old": datetime.now(UTC) - timedelta(days=31),
                "application_id": application_id,
            },
        )
        await session.commit()
    cleaned = await client.get("/api/v1/registration-applications", headers=admin_headers)
    assert cleaned.json()["total"] == 0


@pytest.mark.asyncio
async def test_registration_enforces_node_ip_rate_limits_and_pending_capacity(
    client: AsyncClient,
    app: FastAPI,
) -> None:
    token = "registration-secret-token-value-123"
    body, headers = signed_registration(token)
    first = await client.post(
        "/api/node/v1/registration-applications",
        content=body,
        headers=headers,
    )
    second_body, second_headers = signed_registration(
        token,
        nonce="22222222222222222222222222222222",
    )
    second = await client.post(
        "/api/node/v1/registration-applications",
        content=second_body,
        headers=second_headers,
    )
    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["code"] == "REGISTRATION_RATE_LIMITED"

    now = datetime.now(UTC) - timedelta(minutes=2)
    async with app.state.session_factory() as session:
        values = {
            f"id_{index}": f"capacity-{index:04d}"
            for index in range(999)
        }
        for index, application_id in enumerate(values.values()):
            await session.execute(
                text(
                    "INSERT INTO registration_applications "
                    "(id,node_id,reported_name,hostname,software_version,raw_body,"
                    "request_path,auth_timestamp,auth_nonce,auth_signature,source_ip,"
                    "status,received_at,status_changed_at) "
                    "VALUES (:id,:node_id,'node','host','0.1',x'7b7d','/path','0',"
                    "'00000000000000000000000000000000',"
                    "'0000000000000000000000000000000000000000000000000000000000000000',"
                    "'seed','pending',:received_at,:received_at)"
                ),
                {
                    "id": application_id,
                    "node_id": f"018f47a2-4b5c-7def-8123-{index:012x}",
                    "received_at": now,
                },
            )
        await session.commit()
    capacity_body, capacity_headers = signed_registration(
        token,
        node_id="018f47a2-4b5c-7def-8123-456789abcdee",
        nonce="33333333333333333333333333333333",
    )
    full = await client.post(
        "/api/node/v1/registration-applications",
        content=capacity_body,
        headers=capacity_headers,
    )
    assert full.status_code == 429
    assert full.json()["code"] == "REGISTRATION_CAPACITY_REACHED"


@pytest.mark.asyncio
async def test_approval_rejects_a_token_already_used_by_another_node(
    client: AsyncClient,
) -> None:
    token = "registration-secret-token-value-123"
    for node_id, nonce in (
        ("018f47a2-4b5c-7def-8123-456789abcdef", "44444444444444444444444444444444"),
        ("018f47a2-4b5c-7def-8123-456789abcdee", "55555555555555555555555555555555"),
    ):
        body, headers = signed_registration(token, node_id=node_id, nonce=nonce)
        assert (
            await client.post(
                "/api/node/v1/registration-applications",
                content=body,
                headers=headers,
            )
        ).status_code == 202
    admin_headers = await login_headers(client)
    applications = (
        await client.get(
            "/api/v1/registration-applications?page=1&page_size=20",
            headers=admin_headers,
        )
    ).json()["items"]

    first = await client.post(
        f"/api/v1/registration-applications/{applications[1]['id']}/approve",
        headers=admin_headers,
        json={"token": token},
    )
    duplicate = await client.post(
        f"/api/v1/registration-applications/{applications[0]['id']}/approve",
        headers=admin_headers,
        json={"token": token},
    )
    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "code": "REGISTRATION_TOKEN_DUPLICATE",
        "message": "Token 已被其他接入节点使用",
    }


@pytest.mark.asyncio
async def test_registration_limits_a_source_ip_to_ten_submissions_per_minute(
    client: AsyncClient,
) -> None:
    token = "registration-secret-token-value-123"
    responses = []
    for index in range(11):
        body, headers = signed_registration(
            token,
            node_id=f"018f47a2-4b5c-7def-8123-{index:012x}",
            nonce=f"{index:032x}",
        )
        responses.append(
            await client.post(
                "/api/node/v1/registration-applications",
                content=body,
                headers=headers,
            )
        )

    assert [response.status_code for response in responses[:10]] == [202] * 10
    assert responses[10].status_code == 429
    assert responses[10].json()["code"] == "REGISTRATION_RATE_LIMITED"
