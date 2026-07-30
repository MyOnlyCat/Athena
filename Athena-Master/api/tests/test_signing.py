from app.services.signing import verify_request_signature


def test_request_signature_matches_node_fixed_vector() -> None:
    assert verify_request_signature(
        secret="node-secret",
        method="POST",
        path_with_query="/api/node/v1/nodes/node-1/tasks/claim?limit=2",
        timestamp="1785333600",
        nonce="nonce-123",
        body=b'{"running_tasks":0}',
        signature="89fc0647ffaec69188abcac1bc0eb747ac6bf869a35aac18753dfa9ee6e70caa",
    )


def test_request_signature_rejects_changed_exact_body() -> None:
    assert not verify_request_signature(
        secret="node-secret",
        method="POST",
        path_with_query="/api/node/v1/nodes/node-1/tasks/claim?limit=2",
        timestamp="1785333600",
        nonce="nonce-123",
        body=b'{"running_tasks":1}',
        signature="89fc0647ffaec69188abcac1bc0eb747ac6bf869a35aac18753dfa9ee6e70caa",
    )
