class FakeSSHClient:
    def __init__(self) -> None:
        self.fingerprint = "SHA256:first"
        self.error_code: str | None = None

    async def test_connection(self, connection):
        if self.error_code:
            return {"status": "failed", "code": self.error_code, "message": "连接失败"}
        return {
            "status": "pending_trust",
            "code": "SSH_HOST_KEY_UNTRUSTED",
            "message": "请确认主机指纹",
            "fingerprint": self.fingerprint,
        }


def auth_headers(client) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_host(client, headers, **overrides):
    payload = {
        "name": "node-local",
        "address": "10.0.0.10",
        "port": 22,
        "username": "root",
        "password": "SshPassw0rd!",
        "tags": ["production"],
        "is_local": True,
    }
    payload.update(overrides)
    return client.post("/api/v1/hosts", headers=headers, json=payload)


def test_host_password_is_never_returned_and_edit_can_preserve_it(client):
    headers = auth_headers(client)
    created = create_host(client, headers)

    assert created.status_code == 201
    assert created.json()["has_password"] is True
    assert "password" not in created.json()
    assert "encrypted_password" not in created.json()

    updated = client.put(
        f"/api/v1/hosts/{created.json()['id']}",
        headers=headers,
        json={
            "name": "renamed",
            "address": "10.0.0.10",
            "port": 22,
            "username": "root",
            "tags": ["production"],
            "is_local": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "renamed"
    assert updated.json()["has_password"] is True


def test_only_one_current_node_host_is_allowed(client):
    headers = auth_headers(client)
    assert create_host(client, headers).status_code == 201

    duplicate = create_host(
        client,
        headers,
        name="another-local",
        address="10.0.0.11",
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "LOCAL_HOST_EXISTS"


def test_first_seen_fingerprint_requires_trust_and_changed_key_is_rejected(client):
    headers = auth_headers(client)
    host = create_host(client, headers).json()
    fake = FakeSSHClient()
    client.app.state.ssh_client = fake

    first = client.post(f"/api/v1/hosts/{host['id']}/test", headers=headers)
    assert first.status_code == 200
    assert first.json()["code"] == "SSH_HOST_KEY_UNTRUSTED"
    assert first.json()["fingerprint"] == "SHA256:first"

    trusted = client.post(
        f"/api/v1/hosts/{host['id']}/trust-fingerprint",
        headers=headers,
        json={"fingerprint": "SHA256:first"},
    )
    assert trusted.status_code == 200
    assert trusted.json()["host_key_fingerprint"] == "SHA256:first"

    fake.fingerprint = "SHA256:changed"
    changed = client.post(f"/api/v1/hosts/{host['id']}/test", headers=headers)
    assert changed.status_code == 200
    assert changed.json()["code"] == "SSH_HOST_KEY_CHANGED"
    assert changed.json()["fingerprint"] == "SHA256:changed"
