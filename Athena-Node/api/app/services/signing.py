import hashlib
import hmac


def sign_request(
    *,
    secret: str,
    method: str,
    path_with_query: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    canonical = "\n".join(
        (
            method.upper(),
            path_with_query,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        )
    )
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()

