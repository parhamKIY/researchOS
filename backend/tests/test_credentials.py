import base64
import uuid

import pytest

from researchos.core.credentials import CredentialCipher, CredentialUnavailable

KEY = base64.urlsafe_b64encode(b"0" * 32).decode()


def test_authenticated_encryption_random_nonce_and_owned_context():
    cipher = CredentialCipher(KEY)
    owner, provider = uuid.uuid4(), uuid.uuid4()
    secret = "explicit-test-key-not-a-live-credential"
    first = cipher.encrypt(secret, owner, provider)
    second = cipher.encrypt(secret, owner, provider)
    assert first != second and secret not in first
    assert cipher.decrypt(first, owner, provider) == secret
    for wrong_owner, wrong_provider in [(uuid.uuid4(), provider), (owner, uuid.uuid4())]:
        with pytest.raises(CredentialUnavailable):
            cipher.decrypt(first, wrong_owner, wrong_provider)
    with pytest.raises(CredentialUnavailable):
        cipher.decrypt(first[:-4] + "AAAA", owner, provider)


def test_missing_and_wrong_keys_fail_without_echoing_secret():
    owner, provider = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(CredentialUnavailable):
        CredentialCipher(None).encrypt("fixture", owner, provider)
    stored = CredentialCipher(KEY).encrypt("private fixture", owner, provider)
    with pytest.raises(CredentialUnavailable) as error:
        CredentialCipher(base64.urlsafe_b64encode(b"1" * 32).decode()).decrypt(
            stored, owner, provider
        )
    assert "private fixture" not in str(error.value)
