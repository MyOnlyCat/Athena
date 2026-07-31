import hashlib
import hmac
import json
from datetime import UTC, datetime

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
    nonce = "0123456789abcdef0123456789abcdef"
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
    assert pending_status.status_code == 404
    assert pending_status.json()["code"] == "NODE_NOT_APPROVED"
    assert pending_status.status_code == 404
    assert pending_status.json()["code"] == "NODE_NOT_APPROVED"
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
