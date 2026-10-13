# Local development

Implemented scope: health/typed API docs; account provisioning, opaque session authentication and CSRF; owned projects/private PDFs; PDF.js preview; versioned page text, heuristic section spans, unverified metadata and raster images; durable Celery ingestion/progress/retry and expired-lease recovery; private cleanup; migrations; Compose; locked dependencies; CI checks.

Provider settings and AI analysis remain pending. Upload queues local extraction by default and needs no paid API key. Extraction limitations and verification are recorded in [stage 3](MILESTONE_03.md) and [parser evaluation](PARSER_EVALUATION.md).

## Run locally

Requirements: Docker Desktop with Linux containers and Docker Compose; Python 3.11+ to generate local configuration.

From the repository root:

```powershell
python scripts/bootstrap_env.py
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
```

Open [the workspace](http://localhost:3000) and [generated API docs](http://localhost:3000/api/docs).

Create your account from an interactive terminal, replacing the sample email with your own:

```powershell
docker compose exec api python -m researchos.cli create-user --email you@example.com
```

The command prompts for a 12–256 character password and confirmation without echoing it. Passwords are salted scrypt hashes; no password argument or public registration endpoint is supported. Sign in through the workspace, create a project, select its card to filter/assign uploads, and upload a PDF. Select a paper to rename, display pages, download or delete it. Deleting a project preserves library papers.

Only the frontend is published, on loopback. PostgreSQL, Redis, API and maintenance remain internal. The migration container must complete before API/worker/maintenance startup. Readiness requires the expected database migration and a Redis response; liveness does not require either. Worker availability is verified separately through its healthcheck and a real queued task. Maintenance health checks its last successful sweep.

Private originals live in the `private-files` named volume shared by API, worker and maintenance. PostgreSQL and originals survive container recreation. Backup/restore procedures are still pending; persistence is not a backup. The API runs as UID 10001 and creates original files with mode 0600.

Uploads default to 25 MiB and time out after 90 seconds; `RESEARCHOS_MAX_UPLOAD_BYTES` can change the size up to 100 MiB. Raw uploads carry `Content-Type: application/pdf`, the session CSRF header and an idempotency key. Header/end-marker acceptance does not prove structural validity. Password-protected and malformed PDFs may be stored but fail extraction with a safe error. PDF.js renders pages without document scripts or interactive annotations; worker, fonts and maps are served locally rather than through a CDN.

New uploads create durable ingestion jobs; open the paper to see progress, select extraction history, inspect page text/sections and jump from an image to its source page. Failed jobs expose Retry; completed jobs expose Extract new version. Original files and historical successful results remain available. Deletion is blocked while work is active. Set `RESEARCHOS_AUTO_INGEST_UPLOADS=false` only when storage-only uploads are wanted.

Default parser limits are 200 pages, 100 raster images, 2 million text code points, 16 million pixels/image, 10 MiB/image and 100 MiB total image output. Subprocess wall time defaults to 60 seconds, Linux address-space limit to 1024 MiB and lease to 90 seconds; configurable values are shown in `.env.example`. These are bounds, not a promise that every PDF within them succeeds. Extraction runs in a separate process with scrubbed application credentials; Unix resource limits apply in the Linux container, not on a Windows host. It is not an OS security sandbox. Source PDFs are untrusted; OCR, vector-figure extraction and structured tables are not implemented.

Maintenance retries pending deletions every minute, expires old upload replay records, and removes unreferenced generated files/temporary uploads older than 24 hours. To run one sweep manually:

```powershell
docker compose exec api python -m researchos.cli cleanup-storage
```

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

This uses a separate test image and checks migrated PostgreSQL constraints, ORM/migration agreement, authentication/CSRF/ownership, real parser subprocesses, atomic publication rollback, lease fencing/recovery, explicit broker-outage mocks, private ranges and an 11 MiB concurrent upload through the frontend. A real HTTP/Celery ingestion check verifies pages/images/version history, duplicate delivery and failed-job retry. Most database fixtures roll back. Runtime tests provision uniquely named disposable accounts and remove only their own records/files in `finally`. No provider credentials are used. Integration tests are opt-in and never silently replaced by SQLite or fake Redis.

## Frontend checks

Node.js 22 is required; npm uses `frontend/package-lock.json`.
PDF.js requires Node 22.13 or later within the supported Node 22 series. The `predev`/`prebuild` script copies locked PDF.js assets into Git-ignored `frontend/public/pdfjs/`; Docker copies these generated assets into the runtime image.

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

## Stage 2 acceptance

Implemented and checked locally: login/logout/session invalidation, project lifecycle and ownership, paper storage/replay/deduplication, metadata revisions, project-filtered search, private file ranges, deletion retries and abandoned-file reconciliation. The browser workflow used a disposable local account and a synthetic PDF; the project and original remained available after rebuilding/recreating the application containers. PDF.js successfully displayed the stored page. A separate HTTP integration check used the actual frontend proxy and concurrent 11 MiB uploads and verified one reused paper.

Execution totals and current limitations are recorded in [the stage 2 checkpoint](MILESTONE_02.md). Remote GitHub Actions execution and real AI providers are not included in local verification.

## Network diagnostics

Stage 3 acceptance, current limits and local execution totals are recorded in [the extraction checkpoint](MILESTONE_03.md). The selected parser has also been executed through its real Linux child-process runner on three public research PDFs; see [the evaluation record](PARSER_EVALUATION.md).

If an image pull fails, distinguish host registry access, Docker engine image access, and package access inside a container/build. A registry timeout is not evidence of an application failure. Do not expose `.env` through `docker compose config` output; use `--quiet`.

Standard Compose files intentionally keep official upstream image references. Local image caching/import for network diagnosis is outside application source and must not change declared runtime behavior.

Technical references: [Compose dependency conditions](https://docs.docker.com/reference/compose-file/services/), [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Next.js installation](https://nextjs.org/docs/app/getting-started/installation), [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [PDF.js examples](https://mozilla.github.io/pdf.js/examples/index.html).
