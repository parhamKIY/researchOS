# Foundation development

Implemented scope: FastAPI health endpoints and generated API docs; Next.js status page; validated server configuration; PostgreSQL identity/session schema and Alembic migration; Redis/Celery connectivity test task; Compose; locked dependencies; CI checks.

Authentication endpoints, projects, PDF uploads, AI analysis, durable document-job dispatch, and provider settings are not implemented. The session tables are persistence groundwork, not working authentication. No paid API key is required for this milestone.

## Run locally

Requirements: Docker Desktop with Linux containers and Docker Compose; Python 3.11+ to generate local configuration.

From the repository root:

```powershell
python scripts/bootstrap_env.py
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
```

Open [the workspace](http://localhost:3000) and [generated API docs](http://localhost:3000/api/docs).

Only the frontend is published, on loopback. PostgreSQL, Redis, and the API remain internal. The migration container must complete before API/worker startup. Readiness requires the expected database migration and a Redis response; liveness does not require either. Worker availability is verified separately through its healthcheck and a real queued task.

The environment generator preserves an existing `.env` and never prints secrets. `.env` is ignored by Git and excluded from image contexts. Do not replace its database password after persistent PostgreSQL storage has been initialized without deliberately rotating the database credential as well.

Stop this project's containers without removing persistent data:

```powershell
docker compose down
```

Do not add `--volumes` unless intentionally deleting this project's stored data.

## Backend checks

The backend uses Python 3.11 and `uv` 0.12.2. `backend/uv.lock` locks application and development dependencies.

```powershell
cd backend
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest -m "not integration"
```

Run PostgreSQL/Redis/worker integration checks after the stack is ready, from the repository root:

```powershell
docker compose --profile test run --build --rm tests
```

This uses a separate test image and checks actual migrated PostgreSQL constraints, ORM/migration agreement, API readiness, and a real Celery request/result round trip. Test writes roll back; no user password or provider credential is created. Integration tests are opt-in outside this container and are never silently replaced by SQLite or a fake Redis server.

## Frontend checks

Node.js 22 is required; npm uses `frontend/package-lock.json`.

```powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

The health UI rejects failed, malformed, or disconnected responses instead of showing false readiness. Type generation precedes type checking on a clean checkout. Fonts and visual assets do not require external downloads.

Lint uses ESLint 10, TypeScript ESLint, and React Hooks rules. The Next.js preset was excluded because its transitive glob dependency has an unpatched security advisory and its older React rules fail against ESLint 10. Next.js behavior is also checked through type generation, production builds, and browser verification. Dependency versions are locked; audit findings trigger reviewed upgrades, not an automatic forced downgrade.

## Run application code on the host

The optional development overlay exposes only loopback ports: PostgreSQL 55432, Redis 56379, API 8000.

```powershell
docker compose -f compose.yaml -f compose.dev.yaml up -d --build postgres redis migrate worker
```

For a host API, override the URLs in that shell to point to loopback. Use the existing generated database password without printing it:

```powershell
$localConfig = @{}
Get-Content .env | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $localConfig[$matches[1]] = $matches[2] }
}
$env:RESEARCHOS_DATABASE_URL = "postgresql+psycopg://researchos:$($localConfig['POSTGRES_PASSWORD'])@127.0.0.1:55432/researchos"
$env:RESEARCHOS_REDIS_URL = 'redis://127.0.0.1:56379/0'
$env:RESEARCHOS_SESSION_SECRET = $localConfig['RESEARCHOS_SESSION_SECRET']
cd backend
uv sync --frozen
uv run --frozen uvicorn researchos.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --no-access-log
```

In another shell:

```powershell
cd frontend
$env:API_INTERNAL_URL = 'http://127.0.0.1:8000'
$env:NEXT_TELEMETRY_DISABLED = '1'
npm ci
npm run dev
```

The backend URL is server-only. Next.js rewrites are evaluated during development/build; changing the container routing target requires a frontend rebuild. No `NEXT_PUBLIC` secret configuration is used.

## Migrations and checks

```powershell
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic check
docker compose exec worker celery -A researchos.tasks.celery_app:app inspect ping --destination=worker@researchos
```

New migrations must update the expected schema revision used by readiness and must pass `alembic check`. Never use metadata `create_all()` as a migration substitute.

CI runs backend checks, frontend checks/build, and the complete Compose integration path. A workflow being configured does not mean a remote run has passed; execution evidence is recorded separately.

## Verified foundation checkpoint — 2026-10-13

- All five running services passed Compose healthchecks; the migration container completed successfully.
- Backend: 21 tests passed against the latest test image, including PostgreSQL integrity, migration agreement, error redaction, and a real Celery round trip.
- Frontend: 3 response-trust tests passed; ESLint, TypeScript checks, and the Next.js 16.4.0 production build passed.
- The workspace, same-origin readiness route, and generated OpenAPI document responded successfully. API and frontend containers run as non-root users.
- NPM bulk advisory lookup against the final lockfile reported zero matching advisories. The local npm audit CLI also encountered transient connection resets; the successful bulk response is not a claim that remote CI has passed.
- The initial layout was inspected in the browser. Login, uploads, document analysis, and durable document job dispatch remain pending.
- No README update was made. Local secrets and diagnostic image caches remain Git-ignored.

Development workflow: commit each verified checkpoint immediately; make one push at the end of the work batch. The existing foundation changes were split retrospectively into topical commits after the user corrected the workflow; this does not recreate the original development timing.

## Network diagnostics

If an image pull fails, distinguish host registry access, Docker engine image access, and package access inside a container/build. A registry timeout is not evidence of an application failure. Do not expose `.env` through `docker compose config` output; use `--quiet`.

Standard Compose files intentionally keep official upstream image references. Local image caching/import for network diagnosis is outside application source and must not change declared runtime behavior.

Technical references: [Compose dependency conditions](https://docs.docker.com/reference/compose-file/services/), [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Next.js installation](https://nextjs.org/docs/app/getting-started/installation).
