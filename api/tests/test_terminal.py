from datetime import UTC, datetime, timedelta


def auth_headers(client) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_trusted_host(client, headers) -> dict:
    host = client.post(
        "/api/v1/hosts",
        headers=headers,
        json={
            "name": "terminal-host",
            "address": "10.0.0.20",
            "port": 22,
            "username": "root",
            "password": "SshPassw0rd!",
            "tags": [],
            "is_local": False,
        },
    ).json()
    return client.post(
        f"/api/v1/hosts/{host['id']}/trust-fingerprint",
        headers=headers,
        json={"fingerprint": "SHA256:trusted"},
    ).json()


def test_terminal_ticket_is_one_use_and_short_lived(client):
    headers = auth_headers(client)
    host = create_trusted_host(client, headers)

    response = client.post(
        "/api/v1/terminal/tickets",
        headers=headers,
        json={"host_id": host["id"]},
    )

    assert response.status_code == 201
    ticket = response.json()
    assert ticket["ticket"]
    expires_at = datetime.fromisoformat(ticket["expires_at"])
    assert expires_at <= datetime.now(UTC) + timedelta(seconds=31)

    store = client.app.state.terminal_tickets
    assert store.consume(ticket["ticket"], host["id"]).user_id
    assert store.consume(ticket["ticket"], host["id"]) is None


def test_untrusted_host_cannot_issue_terminal_ticket(client):
    headers = auth_headers(client)
    host = client.post(
        "/api/v1/hosts",
        headers=headers,
        json={
            "name": "untrusted",
            "address": "10.0.0.21",
            "port": 22,
            "username": "root",
            "password": "SshPassw0rd!",
            "tags": [],
            "is_local": False,
        },
    ).json()

    response = client.post(
        "/api/v1/terminal/tickets",
        headers=headers,
        json={"host_id": host["id"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SSH_HOST_UNTRUSTED"

