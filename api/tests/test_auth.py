def test_bootstrap_administrator_can_login(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["user"]["username"] == "admin"
    assert payload["user"]["is_active"] is True


def test_wrong_password_is_rejected_without_leaking_reason(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "incorrect"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_logout_revokes_current_token(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    rejected = client.get("/api/v1/auth/me", headers=headers)
    assert rejected.status_code == 401
    assert rejected.json()["code"] == "TOKEN_REVOKED"


def test_login_is_locked_after_five_failures(client):
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "incorrect"},
        )
        assert response.status_code == 401

    locked = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == "LOGIN_LOCKED"
