import pytest

from app.core.errors import AppError
from app.services.crypto import CredentialCipher


def test_credentials_are_encrypted_and_round_trip(settings):
    cipher = CredentialCipher(settings.credential_key)

    encrypted = cipher.encrypt("SshPassw0rd!")

    assert encrypted != "SshPassw0rd!"
    assert cipher.decrypt(encrypted) == "SshPassw0rd!"


def test_wrong_credential_key_is_reported_as_stable_error(settings):
    encrypted = CredentialCipher(settings.credential_key).encrypt("SshPassw0rd!")
    other = CredentialCipher("1qAz2wSx3eDc4rFv5tGb6yHn7uJm8iKo9pL0aBcDeFg=")

    with pytest.raises(AppError) as error:
        other.decrypt(encrypted)

    assert error.value.code == "CREDENTIAL_DECRYPT_FAILED"

