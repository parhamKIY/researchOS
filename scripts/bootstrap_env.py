"""Generate local-only secrets without displaying them or replacing an existing .env."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / ".env"
password = secrets.token_urlsafe(32)
content = (
    "POSTGRES_USER=researchos\nPOSTGRES_DB=researchos\n"
    f"POSTGRES_PASSWORD={password}\n"
    "RESEARCHOS_ENVIRONMENT=development\n"
    f"RESEARCHOS_DATABASE_URL=postgresql+psycopg://researchos:{password}@postgres:5432/researchos\n"
    "RESEARCHOS_REDIS_URL=redis://redis:6379/0\n"
    f"RESEARCHOS_SESSION_SECRET={secrets.token_urlsafe(48)}\n"
    "RESEARCHOS_PUBLIC_ORIGIN=http://localhost:3000\n"
)
try:
    with destination.open("x", encoding="utf-8") as output:
        output.write(content)
    destination.chmod(0o600)
    print("Created local .env. Secrets were not displayed.")
except FileExistsError:
    print("Existing .env preserved.")
