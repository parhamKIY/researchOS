import base64
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialUnavailable(Exception):
    pass


def decode_key(value: str) -> bytes:
    try:
        key = base64.b64decode(value, altchars=b"-_", validate=True)
        if len(key) != 32:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise CredentialUnavailable("Credential encryption key is invalid") from None


class CredentialCipher:
    def __init__(self, key: str | None):
        self._key = decode_key(key) if key else None

    def _cipher(self):
        if self._key is None:
            raise CredentialUnavailable("Credential encryption is not configured")
        return AESGCM(self._key)

    @staticmethod
    def _context(owner: uuid.UUID, provider: uuid.UUID) -> bytes:
        return f"researchos:provider-key:v1:{owner}:{provider}".encode()

    def encrypt(self, secret: str, owner: uuid.UUID, provider: uuid.UUID) -> str:
        nonce = os.urandom(12)
        payload = self._cipher().encrypt(nonce, secret.encode(), self._context(owner, provider))
        return "v1:" + base64.urlsafe_b64encode(nonce + payload).decode()

    def decrypt(self, encrypted: str, owner: uuid.UUID, provider: uuid.UUID) -> str:
        try:
            if not encrypted.startswith("v1:"):
                raise ValueError
            payload = base64.b64decode(encrypted[3:], altchars=b"-_", validate=True)
            return (
                self._cipher()
                .decrypt(payload[:12], payload[12:], self._context(owner, provider))
                .decode()
            )
        except (ValueError, InvalidTag, UnicodeError):
            raise CredentialUnavailable("Stored credential is unavailable") from None


class SystemCredentialCipher(CredentialCipher):
    @staticmethod
    def _context(owner: uuid.UUID, provider: uuid.UUID) -> bytes:
        return f"researchos:system-key:v1:{provider}".encode()
