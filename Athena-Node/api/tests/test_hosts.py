from typing import Any
from unittest.mock import Mock

import asyncssh
import pytest

from app.services.ssh import AsyncSSHClient, HostConnection


class FakeSSHClient:
    def __init__(self) -> None:
        self.fingerprint = "SHA256:first"
        self.error_code: str | None = None
        self.connections: list[HostConnection] = []

    async def test_connection(self, connection: HostConnection) -> dict[str, Any]:
        self.connections.append(connection)
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


def test_host_probe_settings_are_persisted_and_reschedule_immediately(client):
    headers = auth_headers(client)
    scheduler = client.app.state.host_probe_scheduler
    scheduler.reschedule = Mock()

    default = client.get("/api/v1/hosts/probe-settings", headers=headers)
    updated = client.put(
        "/api/v1/hosts/probe-settings",
        headers=headers,
        json={"interval_minutes": 10},
    )
    persisted = client.get("/api/v1/hosts/probe-settings", headers=headers)

    assert default.status_code == 200
    assert default.json() == {"interval_minutes": 5}
    assert updated.status_code == 200
    assert updated.json() == {"interval_minutes": 10}
    assert persisted.json() == {"interval_minutes": 10}
    scheduler.reschedule.assert_called_once_with()


@pytest.mark.parametrize("interval", [0, 1441, 1.5])
def test_host_probe_interval_rejects_values_outside_integer_range(client, interval):
    headers = auth_headers(client)

    response = client.put(
        "/api/v1/hosts/probe-settings",
        headers=headers,
        json={"interval_minutes": interval},
    )

    assert response.status_code == 422


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
    persisted = client.get(f"/api/v1/hosts/{host['id']}", headers=headers)
    assert persisted.json()["last_test_code"] == "SSH_HOST_KEY_CHANGED"
    assert fake.connections[0].host_key_fingerprint is None
    assert fake.connections[1].host_key_fingerprint == "SHA256:first"


def test_editing_endpoint_clears_trust_but_metadata_edits_preserve_it(client):
    headers = auth_headers(client)
    host = create_host(client, headers, is_local=False).json()
    trusted = client.post(
        f"/api/v1/hosts/{host['id']}/trust-fingerprint",
        headers=headers,
        json={"fingerprint": "SHA256:trusted"},
    ).json()

    metadata = client.put(
        f"/api/v1/hosts/{host['id']}",
        headers=headers,
        json={
            "name": "renamed",
            "address": trusted["address"],
            "port": trusted["port"],
            "username": "deploy",
            "tags": ["staging"],
            "is_local": False,
        },
    )
    endpoint = client.put(
        f"/api/v1/hosts/{host['id']}",
        headers=headers,
        json={
            "name": "renamed",
            "address": trusted["address"],
            "port": 2222,
            "username": "deploy",
            "tags": ["staging"],
            "is_local": False,
        },
    )

    assert metadata.status_code == 200
    assert metadata.json()["host_key_fingerprint"] == "SHA256:trusted"
    assert endpoint.status_code == 200
    assert endpoint.json()["host_key_fingerprint"] is None


class FakeServerKey:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    def get_fingerprint(self, algorithm: str) -> str:
        assert algorithm == "sha256"
        return self.fingerprint


@pytest.mark.asyncio
async def test_saved_connection_test_rejects_changed_key_in_asyncssh_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    async def reject_changed_key(
        host: str,
        port: int,
        **kwargs: Any,
    ) -> Any:
        del host, port
        observed.update(kwargs)
        validator = kwargs["client_factory"]()
        accepted = validator.validate_host_public_key(
            "node.example.com",
            "192.0.2.10",
            22,
            FakeServerKey("SHA256:changed"),
        )
        assert accepted is False
        raise asyncssh.HostKeyNotVerifiable("Host key is not trusted")

    monkeypatch.setattr(asyncssh, "connect", reject_changed_key)
    connection = HostConnection(
        "node.example.com",
        22,
        "root",
        "secret",
        host_key_fingerprint="SHA256:trusted",
    )

    with pytest.raises(asyncssh.HostKeyNotVerifiable):
        await AsyncSSHClient().test_connection(connection)

    assert observed["known_hosts"]
    assert observed["known_hosts"] is not None
    assert callable(observed["client_factory"])
