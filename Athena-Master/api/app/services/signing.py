import hashlib
import hmac


def verify_request_signature(
    *,
    secret: str,
    method: str,
    path_with_query: str,
    timestamp: str,
    nonce: str,
    body: bytes,
    signature: str,
) -> bool:
    canonical = "\n".join(
        (
            method.upper(),
            path_with_query,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        )
    )
    expected = hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
