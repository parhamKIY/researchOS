import hashlib
import hmac
import secrets

SCRYPT_N = 2**17


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=8, p=1, maxmem=256 * 1024 * 1024, dklen=32
    )


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 320 or value.count("@") != 1 or any(c.isspace() for c in value):
        raise ValueError("Invalid email")
    local, host = value.split("@")
    if not local or "." not in host or host.startswith(".") or host.endswith("."):
        raise ValueError("Invalid email")
    return value


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    salt = secrets.token_bytes(16)
    return f"scrypt${SCRYPT_N}$8$1${salt.hex()}${_derive(password, salt).hex()}"


def verify_password(encoded: str | None, password: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = (encoded or dummy_hash).split("$")
        if (algorithm, n, r, p) != ("scrypt", str(SCRYPT_N), "8", "1"):
            return False
        return (
            hmac.compare_digest(_derive(password, bytes.fromhex(salt)).hex(), expected)
            and encoded is not None
        )
    except (ValueError, TypeError):
        return False


# Verify an absent account too, so account existence does not skip password work.
dummy_hash = hash_password(secrets.token_urlsafe(32))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode(), b"csrf:" + token.encode(), hashlib.sha256).hexdigest()
