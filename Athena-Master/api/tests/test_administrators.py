import asyncio

import pytest
from httpx import AsyncClient


async def login_headers(
    client: AsyncClient,
    username: str = "admin",
    password: str = "AdminPassword123",
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_admin_can_list_administrators_with_server_pagination(
    client: AsyncClient,
) -> None:
    headers = await login_headers(client)
    created = await client.post(
        "/api/v1/administrators",
        headers=headers,
        json={"username": "operator", "password": "OperatorPassword123"},
    )
    assert created.status_code == 201

    response = await client.get(
        "/api/v1/administrators?page=2&page_size=1",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": response.json()["items"][0]["id"],
                "username": "operator",
                "is_active": True,
                "last_login_at": None,
                "created_at": response.json()["items"][0]["created_at"],
            }
        ],
        "page": 2,
        "page_size": 1,
        "total": 2,
    }


@pytest.mark.asyncio
async def test_admin_can_create_an_administrator_and_normalized_duplicates_are_rejected(
    client: AsyncClient,
) -> None:
    headers = await login_headers(client)

    created = await client.post(
        "/api/v1/administrators",
        headers=headers,
        json={"username": " operator ", "password": "OperatorPassword123"},
    )
    duplicate = await client.post(
        "/api/v1/administrators",
        headers=headers,
        json={"username": "OPERATOR", "password": "AnotherPassword456"},
    )

    assert created.status_code == 201
    assert created.json()["username"] == "operator"
    assert created.json()["is_active"] is True
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "code": "USERNAME_EXISTS",
        "message": "用户名已存在",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("short-password", "Short1"),
        ("no-letter", "123456789012"),
        ("no-number", "abcdefghijkl"),
        ("admin12345678", "admin12345678"),
    ],
)
async def test_create_administrator_enforces_password_policy(
    client: AsyncClient,
    username: str,
    password: str,
) -> None:
    headers = await login_headers(client)

    response = await client.post(
        "/api/v1/administrators",
        headers=headers,
        json={"username": username, "password": password},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "INVALID_PASSWORD",
        "message": "密码须为 12–128 个字符，且同时包含字母和数字，并且不能与用户名相同",
    }


@pytest.mark.asyncio
async def test_admin_can_disable_and_enable_another_admin_but_not_self(
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
    operator_headers = await login_headers(client, "operator", "OperatorPassword123")

    disabled = await client.patch(
        f"/api/v1/administrators/{operator_id}/status",
        headers=headers,
        json={"is_active": False},
    )
    blocked_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "OperatorPassword123"},
    )
    enabled = await client.patch(
        f"/api/v1/administrators/{operator_id}/status",
        headers=headers,
        json={"is_active": True},
    )
    restored_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "OperatorPassword123"},
    )
    old_session = await client.get("/api/v1/auth/me", headers=operator_headers)
    self_disable = await client.patch(
        f"/api/v1/administrators/{current['id']}/status",
        headers=headers,
        json={"is_active": False},
    )

    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert blocked_login.status_code == 403
    assert blocked_login.json()["code"] == "USER_DISABLED"
    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True
    assert restored_login.status_code == 200
    assert old_session.status_code == 401
    assert old_session.json()["code"] == "TOKEN_REVOKED"
    assert self_disable.status_code == 409
    assert self_disable.json() == {
        "code": "CANNOT_DISABLE_SELF",
        "message": "不能禁用当前登录管理员",
    }


@pytest.mark.asyncio
async def test_password_reset_revokes_all_existing_tokens_for_the_admin(
    client: AsyncClient,
) -> None:
    admin_headers = await login_headers(client)
    created = await client.post(
        "/api/v1/administrators",
        headers=admin_headers,
        json={"username": "operator", "password": "OperatorPassword123"},
    )
    operator_id = created.json()["id"]
    first_headers = await login_headers(client, "operator", "OperatorPassword123")
    second_headers = await login_headers(client, "operator", "OperatorPassword123")

    reset = await client.post(
        f"/api/v1/administrators/{operator_id}/reset-password",
        headers=admin_headers,
        json={"password": "ChangedPassword456"},
    )
    first_session = await client.get("/api/v1/auth/me", headers=first_headers)
    second_session = await client.get("/api/v1/auth/me", headers=second_headers)
    old_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "OperatorPassword123"},
    )
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "ChangedPassword456"},
    )

    assert reset.status_code == 204
    assert first_session.status_code == 401
    assert first_session.json()["code"] == "TOKEN_REVOKED"
    assert second_session.status_code == 401
    assert second_session.json()["code"] == "TOKEN_REVOKED"
    assert old_login.status_code == 401
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_concurrent_disables_cannot_remove_the_last_active_admin(
    client: AsyncClient,
) -> None:
    admin_headers = await login_headers(client)
    admin = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()
    created = await client.post(
        "/api/v1/administrators",
        headers=admin_headers,
        json={"username": "operator", "password": "OperatorPassword123"},
    )
    operator = created.json()
    operator_headers = await login_headers(client, "operator", "OperatorPassword123")

    disable_operator, disable_admin = await asyncio.gather(
        client.patch(
            f"/api/v1/administrators/{operator['id']}/status",
            headers=admin_headers,
            json={"is_active": False},
        ),
        client.patch(
            f"/api/v1/administrators/{admin['id']}/status",
            headers=operator_headers,
            json={"is_active": False},
        ),
    )

    statuses = sorted([disable_operator.status_code, disable_admin.status_code])
    assert statuses[0] == 200
    assert statuses[1] in {401, 409}
    rejected = disable_admin if disable_admin.status_code != 200 else disable_operator
    assert rejected.json()["code"] in {"TOKEN_REVOKED", "LAST_ACTIVE_ADMIN"}
    active_headers = admin_headers if disable_operator.status_code == 200 else operator_headers
    listed = await client.get(
        "/api/v1/administrators?page=1&page_size=20",
        headers=active_headers,
    )
    assert listed.status_code == 200
    assert sum(item["is_active"] for item in listed.json()["items"]) == 1
