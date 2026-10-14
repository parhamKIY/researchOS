"""Generate local-only secrets, preserving existing database/session credentials."""

import base64
import os
import secrets
from pathlib import Path


def bootstrap(root: Path) -> str:
    destination = root / ".env"
    encryption_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    password = secrets.token_urlsafe(32)
    content = (
        "POSTGRES_USER=researchos\nPOSTGRES_DB=researchos\n"
        f"POSTGRES_PASSWORD={password}\n"
        "RESEARCHOS_ENVIRONMENT=development\n"
        f"RESEARCHOS_DATABASE_URL=postgresql+psycopg://researchos:{password}@postgres:5432/researchos\n"
        "RESEARCHOS_REDIS_URL=redis://redis:6379/0\n"
        f"RESEARCHOS_SESSION_SECRET={secrets.token_urlsafe(48)}\n"
        f"RESEARCHOS_CREDENTIAL_ENCRYPTION_KEY={encryption_key}\n"
        "RESEARCHOS_PUBLIC_ORIGIN=http://localhost:3000\n"
    )
    try:
        with destination.open("x", encoding="utf-8") as output:
            destination.chmod(0o600)
            output.write(content)
        return "Created local .env. Secrets were not displayed."
    except FileExistsError:
        existing = destination.read_text(encoding="utf-8")
        if any(
            line.startswith("RESEARCHOS_CREDENTIAL_ENCRYPTION_KEY=")
            for line in existing.splitlines()
        ):
            return "Existing .env and encryption key preserved."
        with destination.open("a", encoding="utf-8") as output:
            destination.chmod(0o600)
            output.write(f"\nRESEARCHOS_CREDENTIAL_ENCRYPTION_KEY={encryption_key}\n")
        return "Existing credentials preserved; added local encryption key without displaying it."


if __name__ == "__main__":
    print(bootstrap(Path(__file__).resolve().parents[1]))
