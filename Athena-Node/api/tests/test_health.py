def test_health_returns_service_state(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "athena-node-api"}


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/missing", headers={"X-Request-Id": "request-123"})

    assert response.status_code == 404
    assert response.json() == {
        "code": "HTTP_NOT_FOUND",
        "message": "请求的资源不存在",
        "request_id": "request-123",
        "details": {},
    }
    assert response.headers["X-Request-Id"] == "request-123"
