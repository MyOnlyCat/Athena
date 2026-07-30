from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import AppError


class CredentialCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise AppError(
                "CREDENTIAL_DECRYPT_FAILED",
                "SSH 凭据无法解密",
                status_code=500,
            ) from exc

