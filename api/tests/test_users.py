def login_headers(client) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_can_create_disable_enable_and_reset_user(client):
    headers = login_headers(client)
    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "operator", "password": "OperatorPassw0rd!"},
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    disabled = client.patch(
        f"/api/v1/users/{user_id}/status",
        headers=headers,
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    blocked_login = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "OperatorPassw0rd!"},
    )
    assert blocked_login.status_code == 403
    assert blocked_login.json()["code"] == "USER_DISABLED"

    assert client.patch(
        f"/api/v1/users/{user_id}/status",
        headers=headers,
        json={"is_active": True},
    ).status_code == 200
    assert client.post(
        f"/api/v1/users/{user_id}/reset-password",
        headers=headers,
        json={"password": "ChangedPassw0rd!"},
    ).status_code == 204
    assert client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "ChangedPassw0rd!"},
    ).status_code == 200


def test_current_user_cannot_disable_self(client):
    headers = login_headers(client)
    current = client.get("/api/v1/auth/me", headers=headers).json()

    response = client.patch(
        f"/api/v1/users/{current['id']}/status",
        headers=headers,
        json={"is_active": False},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CANNOT_DISABLE_SELF"


def test_duplicate_username_is_case_insensitive(client):
    headers = login_headers(client)
    response = client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "ADMIN", "password": "AnotherPassw0rd!"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "USERNAME_EXISTS"
