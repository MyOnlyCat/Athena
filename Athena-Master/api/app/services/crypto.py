import hashlib
import hmac

from cryptography.fernet import Fernet


class CredentialCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()


def node_token_fingerprint(credential_key: str, token: str) -> str:
    return hmac.new(
        credential_key.encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()
