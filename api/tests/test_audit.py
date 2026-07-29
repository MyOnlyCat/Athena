def test_authenticated_mutation_is_visible_in_audit_log(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminPassw0rd!"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    created = client.post(
        "/api/v1/hosts",
        headers=headers,
        json={
            "name": "audited-host",
            "address": "10.0.0.80",
            "port": 22,
            "username": "root",
            "password": "SshPassw0rd!",
            "tags": [],
            "is_local": False,
        },
    )
    assert created.status_code == 201

    logs = client.get("/api/v1/audit-logs", headers=headers)
    assert logs.status_code == 200
    assert any(
        item["action"] == "POST /api/v1/hosts"
        and item["result"] == "success"
        and item["user_id"] == login.json()["user"]["id"]
        for item in logs.json()
    )
