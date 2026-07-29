from app.services.signing import sign_request


def test_request_signature_matches_fixed_vector():
    signature = sign_request(
        secret="node-secret",
        method="POST",
        path_with_query="/api/node/v1/nodes/node-1/tasks/claim?limit=2",
        timestamp="1785333600",
        nonce="nonce-123",
        body=b'{"running_tasks":0}',
    )

    assert signature == "89fc0647ffaec69188abcac1bc0eb747ac6bf869a35aac18753dfa9ee6e70caa"


def test_request_signature_changes_when_body_changes():
    common = {
        "secret": "node-secret",
        "method": "POST",
        "path_with_query": "/api/node/v1/nodes/heartbeat",
        "timestamp": "1785333600",
        "nonce": "nonce-123",
    }

    assert sign_request(body=b"{}", **common) != sign_request(body=b'{"hosts":[]}', **common)
