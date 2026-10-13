import pytest

from researchos.core.security import (
    csrf_token,
    hash_password,
    normalize_email,
    token_hash,
    verify_password,
)


def test_passwords_are_salted_and_verified():
    password = "fixture password 123"
    encoded = hash_password(password)
    assert encoded.startswith("scrypt$131072$8$1$")
    assert encoded != hash_password(password)
    assert verify_password(encoded, password)
    assert not verify_password(encoded, "wrong password")
    assert not verify_password(None, password)
    assert not verify_password("invalid", password)


@pytest.mark.parametrize("password", ["short", "x" * 257])
def test_password_bounds(password):
    with pytest.raises(ValueError):
        hash_password(password)


def test_session_csrf_derivation_is_bound_to_token_and_secret():
    assert csrf_token("session", "secret") == csrf_token("session", "secret")
    assert csrf_token("session", "secret") != csrf_token("other", "secret")
    assert csrf_token("session", "secret") != csrf_token("session", "other")
    assert len(token_hash("session")) == 64
    assert normalize_email(" Person@Example.com ") == "person@example.com"


@pytest.mark.parametrize("email", ["missing-at", "@example.com", "a@localhost", "a b@example.com"])
def test_invalid_email(email):
    with pytest.raises(ValueError):
        normalize_email(email)
