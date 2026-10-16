# Initial REST API contract

Status: version 0.7. Private library/extraction, provider settings, administration, administrator model discovery and stage 5 analysis endpoints are implemented. Chat, retrieval and external literature discovery remain planned. The implemented boundaries below take precedence over broader design sketches. Real-provider analysis and scientific quality have not been verified.

## Implemented stage 4 boundary

- Personal provider CRUD, model CRUD, routing GET/PUT and provider connection tests follow the routes listed below. All require session ownership, with CSRF on mutations and ETags on edits/deletes/routing replacement. Lists have signed cursors and limits 1–100, default 20. Unknown fields, arbitrary endpoints on personal connections, invalid model IDs and forged capability-source fields are rejected. Administrator-managed endpoints are described separately below.
- Supported adapters are `gemini` and `mock`. Provider creation requires a write-only `api_key` for Gemini and forbids it for mock. PATCH adds `clear_credential: true` for removing the saved key; key replacement and clearing cannot occur together. DELETE disables the connection, clears ciphertext and hides it from reads, retaining model/usage history. It does not revoke the external Google key.
- Model IDs match `[A-Za-z0-9][A-Za-z0-9._-]{0,199}`. Capabilities are a nonempty unique subset of `text`, `vision`, `embeddings`, always marked `manual`. Parameters currently allow only optional temperature 0–2 and integer max output tokens 16–8192. Model DELETE disables rather than deleting history; PATCH can reenable.
- Routing tasks are `paper_summary`, `methodology`, `research_gaps`, `paper_chat`, `figure_analysis`, `embeddings`. PUT atomically replaces up to six rules; model/provider ownership, enablement, declared capability and exact allowed provider set are checked. A stale aggregate ETag returns 412. Stage 5 executes approved text fallbacks only after definite request failures; ambiguous outcomes are not automatically replayed.
- `POST /providers/{id}/test` takes `{model_configuration_id}` and tests a text-capable configuration from that exact provider. It sends only a fixed connection message and may consume quota/cost. Expected provider errors return HTTP 200 with `status: failed`, a safe code, mode, checked time, usage IDs and an outcome-unknown flag; local auth/ownership/validation/configuration errors retain standard HTTP errors. Tests are limited to ten recorded attempts/minute per owner before starting a new test; a bounded retry may add a second attempt. Vision and embedding declarations are not verified by this probe.
- `GET /analytics/usage` lists owner-private attempt records: safe names/IDs, task, mode, state, attempt, available input/output/thought/total token counts, latency, nullable cost/currency/source and timestamp. No prompt, output, credential or encrypted value is returned. Mock counts are synthetic. Gemini billing cost is not inferred from token counts.
- The settings UI changes saved models and parameters without restarting the backend. Stage 5 paper reports are described below. Model discovery is implemented for administrator system settings; personal provider model discovery, server encryption-key rotation and spending limits remain unimplemented.
All resource routes below are relative to `/api/v1`.
Related: [architecture](ARCHITECTURE.md), [data model](DATA_MODEL.md).

## Implemented administration boundary

Routes are relative to `/api/v1`. Session responses include `user.is_admin`; every admin request rechecks the stored role. No public endpoint grants roles. Mutations require trusted origin and CSRF.

| Route | Behavior |
|---|---|
| `GET /admin/overview` | Admin-only aggregate account/project/paper counts; no private content. |
| `GET /admin/users` | Admin-only identities, status, role, revision and `etag`; signed cursor, limit 1–100. No password hashes. |
| `PATCH /admin/users/{id}` | Only `{is_active: boolean}` and the account's `If-Match`. Disabling revokes sessions. Own/admin accounts are protected (409). |
| `GET /admin/llm` | Singleton `revision`, `etag`, nullable `active`, latest 20 safe checks. No keys/ciphertext. |
| `POST /admin/llm/models` | Admin + origin/CSRF; `{adapter, base_url?, api_key?}`. Returns `{items: [{id, display_name}], execution_mode}` without saving keys or changing active settings. Blank key reuses only the same active protocol/base URL. Ten requests/min/admin; sanitized upstream errors are 502; unsupported listing is `model_catalog_unsupported`. |
| `POST /admin/llm/verify-and-apply` | Aggregate `If-Match`, `{adapter, model_name, base_url?, api_key?, parameters?}`; returns `{applied, check, settings}`. Expected probe failures return 200 with `applied: false`; active settings stay unchanged. |
| `GET /settings/system-model` | Signed-in users; active model/protocol/parameters/mode/check time, revision and etag. Endpoint/key status/history omitted. |

Admin adapters: `gemini`, `openai_compatible`, `mock`. Gemini accepts only its official HTTPS base. Compatible providers require a public HTTPS base on port 443 without credentials/query/fragment/literal IP; the server appends `/chat/completions`. Compatible model IDs may include `/` and `:`; Gemini keeps its stricter pattern. Keys contain visible ASCII and are write-only. An omitted key is reused only for identical protocol and normalized base. Mock accepts no URL/key.

Probes send one fixed public message, capped at 256 output tokens with bounded time. Admin probes do not retry, follow redirects or use environment proxies. Ten new checks/minute system-wide are allowed, including pending checks. Missing ETag returns 428; stale ETag before/after the test returns 412. Role and session are rechecked before activation. Failed/stale/superseded keys are erased; interrupted probes recover after five minutes. Explicit personal text routes take precedence over the verified system default; an invalid private route never silently falls back. Stage 5 separately enforces paper privacy and exact destination approval.

## Implemented stage 5 analysis boundary

| Route | Behavior |
|---|---|
| `GET /papers/{id}/analysis-plan?document_version_id=...&language=fa` | Owned usable extraction; language `fa`/`en`. Returns fingerprint, safe snapshots of exact primary/fallback destinations, external-processing requirements and context coverage. No keys or raw prompts. |
| `POST /papers/{id}/analyses` | CSRF/origin and `Idempotency-Key`; `AnalysisCreate` below. 202 `{id, state: queued, paper_id}` and Location `/api/v1/analyses/{id}`. |
| `GET /papers/{id}/analyses` | Owned history; signed cursor, default limit 20/max 100. Snapshots, state/progress, language, lineage, timestamps. |
| `GET /analyses/{id}` | Owned report plus sections, validated claims/inline evidence, actual per-section generation identity and usage attempts. Private/no-store. |

Creation requires `document_version_id`, `language`, `plan_fingerprint`, `approved_configuration_ids` matching every reviewed destination. Live targets additionally require `acknowledge_external_processing: true` and `Paper.external_processing_allowed=true`. A stale plan returns 412, foreign IDs 404, destination mismatch 422, private-paper denial 403. One active analysis per paper is enforced in the database; 12 new reports/owner/hour. Idempotency replays for 24 hours before checking current configuration; conflicting payloads return 409.

Optional `retry_of_id` links a failed/partial report on the same owned paper. An uncertain previous outcome requires `acknowledge_unknown_outcome: true` (otherwise 409). Retry creates a full new report, reruns all seven sections and preserves history; there is no analysis retry through `/jobs/{id}/retry`.

Report sections: `overview`, `methodology`, `results`, `limitations`, `future_work`, `research_gaps`, `resources`. Section states: `completed`, `unavailable`, `failed`; unavailable output requires a reason. Claim kinds: `author_claim`, `supported_interpretation`, `ai_suggestion`. Quotes must match supplied Unicode code-point spans exactly. Published witnesses include page ID/number, extraction version via the report, section IDs and absolute page offsets. Numeric result fields must occur in quoted evidence, as must numbers in factual prose and URLs. Resource URLs are document-extracted and unverified; no external links are fetched. Research proposals have explicit motivation/approach/uncertainty and nullable proposed data/models/evaluation, implementation strategy, estimated difficulty/compute and contribution. Suggestions cannot be classified as verified findings or novelty assessments.

Context is bounded to 24,000 extracted characters; long documents use evenly distributed chunks with `sampled_extracted_text` disclosure. This is not full-document retrieval. Exact evidence validates location, not semantic entailment or scientific accuracy. Parser warnings and context coverage are saved with model/parameter, prompt/schema version, language and explicit consent snapshots.

Generation policy `analysis-v1` uses 4096 output tokens when the saved model omits an explicit limit; configured limits remain unchanged. An omitted temperature uses the provider's default, whose numeric value is unknown. The snapshot records configured parameters and the policy version; it does not claim provider-internal sampling settings are known.

The report itself is the durable analysis job (separate from ingestion jobs). Maintenance dispatches queued work; workers claim fenced leases, record attempts before provider I/O, revalidate settings/privacy and publish each validated section independently. A pending paid attempt after worker loss becomes `outcome_unknown`; expired analysis work is never automatically requeued. At most one approved fallback executes for definite rejection/rate/connection errors, never for ambiguous outcomes or invalid model output. Partial results survive failures. Active analysis blocks paper deletion. Usage is available inside the report; missing tokens/cost remain unknown and mock usage is synthetic. Scientific verification remains `not_evaluated` for all reports until separate evaluation exists.

## Implemented stage 2 boundary

- Accounts are provisioned with `python -m researchos.cli create-user --email ...`; there is no signup endpoint. Passwords use salted scrypt (N=131072, r=8, p=1). Login has a shared Redis rate limit of 30 attempts/minute; password verification concurrency is bounded. Infrastructure failure closes login with 503.
- All authentication and project routes below are available. Project deletion preserves papers and increments affected paper revisions when memberships disappear.
- Paper upload uses a **raw `application/pdf` request body**, `filename` and optional `project_id` query parameters, and `Idempotency-Key` plus the session CSRF header. This replaces the earlier multipart proposal and avoids a separate multipart parser. Maximum default size is 25 MiB; uploads time out after 90 seconds. The web proxy allows up to 110 MiB to accommodate the backend's configurable maximum of 100 MiB; the backend enforces the actual configured limit.
- Upload acceptance checks filename, size, PDF header/end marker and owner access. This is not structural parsing, malware scanning, or a guarantee that a PDF can be rendered. New uploads automatically queue ingestion by default, atomically with storage metadata. Reused files do not start another job. `RESEARCHOS_AUTO_INGEST_UPLOADS=false` permits storage-only uploads, with manual ingestion still available.
- Uploads serialize per owner. Same-key/same-content replay returns the original status/body for 24 hours; a different payload returns 409. The payload fingerprint includes content hash, sanitized filename and project. Same-owner content duplicates reuse the original paper; another account gets its own record and private file.
- Paper listing currently supports `q` (literal title/filename substring), `project_id`, `limit`, and signed `cursor`. Tag and processing-state filters remain planned. Cursor scope includes owner, list kind and filters; malformed or mismatched cursors return 422.
- Implemented paper reads contain `id`, nullable user-supplied `title`, `external_processing_allowed`, `project_ids`, `original_name`, `byte_size`, `sha256`, current `processing_state`, nullable latest version/job IDs, revision and timestamps. Storage keys and owner IDs are not serialized. Parsed metadata lives on the document version rather than the paper.
- Implemented paper PATCH supports `title` (nullable to clear), `project_ids` (full replacement), and `external_processing_allowed`. Unknown fields, null membership/privacy fields and duplicate project IDs are rejected. Every project must belong to the account.
- File GET supports private byte ranges and optional `download=true`. PDF.js displays pages locally using bundled worker/fonts/maps; the app does not run document scripts or render interactive annotations. Files also carry a restrictive CSP.
- Deletion commits a cleanup record before removing paper rows; failed file removal retries through maintenance every minute. Old unreferenced generated files and temporary uploads are reconciled after 24 hours. Account deletion remains unexposed.
- Mutable project/paper reads return ETag; PATCH/DELETE require `If-Match` (428 missing, 412 stale). Foreign-owned IDs return the same 404 as absent IDs. JSON mutations are bounded to 16 KiB.

The broader definitions below preserve intended later contracts. The implemented stage 2 boundary above and stage 3 boundary below take precedence for current routes. Additional paper, analysis and provider fields remain planned.

## Shared behavior

- JSON uses snake_case; IDs are UUIDs; timestamps are UTC RFC 3339. Unknown fields in mutation payloads are rejected.
- Authentication uses an opaque HttpOnly cookie. Non-login mutations require `X-CSRF-Token`; login requires a trusted Origin and JSON. Provisioning is CLI-only.
- Missing resources and resources owned by another user both return 404. Invalid authentication returns 401; policy/capability restrictions for an owned resource return 403 or 422 as specified.
- Cursor-paginated responses use `{items, next_cursor}`. `limit` defaults to 20, maximum 100. Opaque cursors validate scope, filters, sort, and tie-breaking ID; malformed cursors return 422. The bounded figure collection uses offsets as specified in the stage 3 boundary.
- List order defaults to descending creation time, then descending ID. Paper lists support bounded `q`, `project_id`, `tag`, and `processing_state`; project lists support `archived`.
- Mutable metadata/configuration reads return an ETag derived from revision. PATCH/PUT/DELETE require `If-Match` for existing mutable projects, papers, providers, models, and routing settings: absent returns 428, stale returns 412. Job/report/file reads are not mutable configuration.
- `Idempotency-Key` is required for upload, ingestion, planned analysis creation, and retry creation. Scope is owner + operation; retain for at least 24 hours. Same key and canonical payload/hash replays its original status/body; different payload returns 409. Uploads and ingestion creation serialize per owner; equivalent active ingestion returns 409.
- Rate limiting returns 429 and `Retry-After`; known temporary infrastructure unavailability returns 503. Provider failures are normalized in the job, not returned as raw SDK exceptions.
- UUID path/query validation and request-schema errors return 422; size overflow 413; unsupported media 415; malformed/nonparseable PDF 422 if caught synchronously or a failed ingestion job otherwise.
- Errors use `{error: {code, message, request_id, details}}`. Details contain safe field issues/owned conflicting IDs, never credentials, document text, raw provider errors, or stack traces.
- Private JSON and file responses use `Cache-Control: private, no-store`; no intermediary may cache user sessions, reports, or provider settings.

Example error (illustrative):

```json
{"error":{"code":"analysis_already_running","message":"An equivalent analysis is active.","request_id":"example-request","details":{"job_id":"00000000-0000-4000-8000-000000000001"}}}
```

## Endpoints

| Method and path | Input | Success / important behavior |
|---|---|---|
| `GET /health/live` | None; public | 200 `{status}`; process alive only |
| `GET /health/ready` | None; public | 200 `{status}` or 503; required database/broker connectivity; no infrastructure details |
| `POST /auth/login` | `LoginRequest` | 200 `SessionRead` + session cookie; invalid credentials 401; generic message |
| `GET /auth/session` | Session cookie | 200 `SessionRead`; 401 if expired |
| `POST /auth/logout` | CSRF header | 204; revoke session and clear cookie |
| `POST /projects` | `ProjectCreate` | 201 `ProjectRead` + Location + ETag |
| `GET /projects` | Pagination, `archived` | 200 paginated `ProjectRead` |
| `GET /projects/{project_id}` | Owned ID | 200 `ProjectRead` + ETag |
| `PATCH /projects/{project_id}` | `ProjectPatch`, If-Match | 200 `ProjectRead` + new ETag |
| `DELETE /projects/{project_id}` | If-Match | 204; remove memberships, preserve library papers |
| `POST /papers/upload` | Raw PDF body; `filename`, optional `project_id`; idempotency key | 201 `UploadRead` + Location for new paper; 200 same-owner duplicate, no new analysis |
| `GET /papers` | Pagination and documented filters | 200 paginated `PaperRead` |
| `GET /papers/{paper_id}` | Owned ID | 200 `PaperRead` + ETag |
| `PATCH /papers/{paper_id}` | `PaperPatch`, If-Match | 200 `PaperRead`; metadata correction, tags, project membership, privacy |
| `DELETE /papers/{paper_id}` | If-Match | 204 after database deletion; 409 if active work; storage cleanup follows durably |
| `GET /papers/{paper_id}/file` | Owned paper | 200 private PDF, supports byte ranges (206); no storage path; `Cache-Control: private, no-store` |
| `GET /papers/{paper_id}/document-versions` | Pagination | 200 version metadata including parse state/warnings |
| `GET /papers/{paper_id}/figures` | `document_version_id`, pagination | 200 paginated `FigureRead` |
| `GET /figures/{figure_id}/file` | Owned figure | 200 private image; safe content type and no-store |
| `POST /papers/{paper_id}/analyses` | `AnalysisCreate`, idempotency key | 202 `{id,state,paper_id}` + report Location; current stage 5 boundary above |
| `GET /jobs/{job_id}` | Owned ID | 200 `JobRead`; initial UI polls with bounded backoff |
| `POST /jobs/{job_id}/retry` | Empty JSON and idempotency key | Ingestion only; analysis retries create a new report using `retry_of_id` |
| `GET /papers/{paper_id}/analyses` | Pagination | 200 paginated `AnalysisSummary` |
| `GET /analyses/{analysis_id}` | Owned ID | 200 `AnalysisRead`, immutable saved report |
| `GET /evidence/{evidence_id}` | Planned separate evidence resource | Not implemented; current reports embed validated witnesses and use owned version/page reads |
| `POST /providers` | `ProviderCreate` | 201 `ProviderRead` + Location + ETag; validate supported adapter |
| `GET /providers` | Pagination | 200 paginated `ProviderRead` |
| `GET /providers/{provider_id}` | Owned ID | 200 `ProviderRead` + ETag |
| `PATCH /providers/{provider_id}` | `ProviderPatch`, If-Match | 200 `ProviderRead`; optional replacement key write-only |
| `DELETE /providers/{provider_id}` | If-Match | 204; disable, revoke key, preserve safe history |
| `POST /providers/{provider_id}/test` | Explicit selected `model_configuration_id` | 200 normalized `{status, checked_at, code}`; no document sent; may incur provider cost, shown before submission |
| `POST /providers/{provider_id}/models` | `ModelCreate` | 201 `ModelRead` + Location + ETag |
| `GET /providers/{provider_id}/models` | Pagination | 200 paginated `ModelRead`; manually configured models first |
| `GET /models/{model_id}` | Owned ID | 200 `ModelRead` + ETag |
| `PATCH /models/{model_id}` | `ModelPatch`, If-Match | 200 `ModelRead`; revision increment; capability validation |
| `DELETE /models/{model_id}` | If-Match | 204; disable; routing to disabled model rejected |
| `GET /settings/model-routing` | Session | 200 `RoutingRead` + aggregate ETag |
| `PUT /settings/model-routing` | `RoutingWrite`, If-Match | 200 `RoutingRead`; atomic full replacement; validate ownership/capabilities |

The provider-test operation performs bounded server-side connectivity testing and always normalizes expected provider errors; authentication, ownership, request-validation and infrastructure failures still use standard HTTP errors. Model discovery is optional later; the initial release supports manual model configuration without pretending the list is exhaustive.

## Payload definitions

Fields are required unless marked `?`. Nullable is stated explicitly. Read objects never contain stored ciphertext, application keys, provider keys, cookie tokens, internal lease tokens, or private storage keys.

| Schema | Fields |
|---|---|
| `LoginRequest` | `email: string`, `password: string` |
| `SessionRead` | `user: {id, email}`, `expires_at: timestamp`, `csrf_token: string` (session-private, no-store) |
| `ProjectCreate` | `name: string[1..200]`, `description?: string[0..5000]` |
| `ProjectPatch` | At least one of `name`, `description`, `archived: bool` |
| `ProjectRead` | `id`, `name`, `description`, nullable `archived_at: timestamp`, `revision`, `created_at`, `updated_at` |
| `PaperPatch` | Optional typed `title`, `authors: string[]`, `publication_year: integer`, `venue`, `doi`, `abstract`; nullable metadata may be cleared; `tags?: string[]`, `project_ids?: UUID[]` (full replacement), `external_processing_allowed?: bool`; at least one field required |
| `PaperRead` | `id`, nullable `title`, `doi`, `abstract`, `publication_year`, `venue`; `authors: string[]`, metadata provenance, `tags`, `project_ids`, `external_processing_allowed`, nullable `latest_document_version_id`, nullable `latest_ingestion_job_id`, `revision`, timestamps |
| `UploadRead` | `paper: PaperRead`, `duplicate: bool`, nullable `ingestion_job: JobRead`; null when no active ingestion exists on reused paper |
| `DocumentVersionRead` | `id`, `paper_id`, `state`, parser name/version/config, unverified `metadata`, `warnings`, `page_count`, `figure_count`, `created_at`, nullable `completed_at` |
| `FigureRead` | `id`, `paper_id`, `document_version_id`, `page_number`, nullable caption and bounding box, `file_url` (owned relative API route), `extraction_method` |
| `AnalysisCreate` | `document_version_id: UUID`, `language: en/fa`, `plan_fingerprint: sha256`, `approved_configuration_ids: UUID[1..6]`, `acknowledge_external_processing?: bool`, `retry_of_id?: UUID`, `acknowledge_unknown_outcome?: bool`; extra fields rejected |
| `RetryRequest` | Ingestion uses empty JSON; analysis retries use the complete `AnalysisCreate` with `retry_of_id` and optional uncertainty acknowledgment |
| `JobRead` | Ingestion ID, paper/version IDs, kind/state/stage, progress_percent, attempt, retry_of_job_id, safe error and timestamps |
| `AnalysisSummary` | Report/paper/version/parent IDs, state, language, progress/stage, safe error, outcome_unknown, created/finished times, frozen `configuration`, `scientific_verification: not_evaluated` |
| `AnalysisRead` | `AnalysisSummary` plus `sections` and safe per-request `usage` |
| `ReportSectionRead` | `kind`, `state: completed/unavailable/failed`, `error_code`, nullable validated `payload` containing items/unavailable_reason and actual server-attached generation identity |
| `ClaimRead` | Inline `kind: author_claim/supported_interpretation/ai_suggestion`, topic, text, exact evidence, nullable structured result/resource/research proposal |
| `EvidenceRead` | Inline chunk reference and relative start/end, quote, page_id/page_number, absolute start_offset/end_offset and section_ids; extraction version belongs to report |
| `ProviderCreate` | `adapter: supported identifier`, `display_name: string[1..100]`, `api_key: write-only string` (not needed for mock) |
| `ProviderPatch` | At least one of `display_name`, `api_key` (replacement), `enabled: bool` |
| `ProviderRead` | `id`, `adapter`, `display_name`, `credential_configured: bool`, fixed nullable `credential_display: string` (no key characters), `enabled`, `revision`, timestamps |
| `ModelCreate` | `model_name: string[1..200]`, `capabilities: string[]` (enum items: `text`, `vision`, `embeddings`), `parameters?: object`; capability source is server-set to `manual` |
| `ModelPatch` | Any of `model_name`, `capabilities`, `parameters`, `enabled`; client cannot set provider_verified |
| `ModelRead` | `id`, `provider_id`, `model_name`, `capabilities`, `capability_source`, `parameters`, `enabled`, `revision`, timestamps |
| `RoutingWrite` | `rules: {task, primary_model_id, fallback_model_id?: UUID, allowed_provider_ids: UUID[]}[]`; fallback may also be null |
| `RoutingRead` | `rules`, `revision`, `updated_at` |

Clients cannot supply capability source; initial manual model configuration is always marked `manual`. Server discovery/verification may promote it later. Empty capabilities or contradictory parameters are rejected. A manually marked capability still may fail at the provider; return a capability error rather than silently switching models.

Metadata corrections are bounded typed fields, not arbitrary JSON; unknown data remains nullable. Analysis consent is an explicit list of providers and does not override `external_processing_allowed=false`. The mock adapter needs no external consent and is always visibly marked.

## Report section contract

Initial kinds: `overview`, `methodology`, `results`, `limitations`, `future_work`, `research_gaps`, `resources`.

- `overview`: short/detailed/beginner summaries, research problem, contributions; key factual statements reference claim IDs.
- `methodology`: components, inputs/outputs, training, losses, algorithms, experimental setup, baselines, and metrics; missing fields remain unavailable rather than guessed.
- `results`: records with nullable metric/dataset/setting/value/unit/baseline and source claim IDs. Keep reported numeric strings faithful to the source; no fabricated aggregate.
- `limitations` and `future_work`: items categorized by claim kind so author statements remain distinct from model interpretations.
- `research_gaps`: suggestions with motivation, supporting claims, uncertainty, proposed approach, possible data/evaluation, and explicitly estimated difficulty/compute. Novelty is not asserted.
- `resources`: only document-extracted names/URLs in the first release, plus evidence and validation status. URL discovery and automatic fetching are deferred.

Each section payload receives a Pydantic schema during implementation and is versioned with the report. Source-statement claims require at least one valid text witness; unsupported or unverified claims cannot masquerade as author statements. Initial evidence validation checks ownership/version/offsets/quote; extraction accuracy and semantic faithfulness need separate evaluation.

## Asynchronous and re-analysis semantics

Upload returns after private storage and durable database/job commit. Parsing runs asynchronously. The planned analysis endpoint requires a usable `ready` or `partially_ready` document version and freezes its configuration. A new idempotency key permits intentional re-extraction/re-analysis after previous work has terminated; equivalent active work returns 409.

### Implemented stage 3 API

| Route | Current behavior |
|---|---|
| `POST /papers/{paper_id}/ingestions` | Empty JSON `{}`, CSRF and idempotency key; 202 job with Location. At most 60 new ingestion jobs per owner/hour; active equivalent work returns 409. |
| `GET /jobs/{job_id}` | Ingestion state, real progress, attempt, version/retry IDs and nullable `error: {code}`. No snapshot, lease or file key. |
| `POST /jobs/{job_id}/retry` | Empty JSON `{}`, CSRF and idempotency key; failed ingestion only. New version/job, 24-hour request replay. Paid analysis retry is still planned. |
| `GET /papers/{paper_id}/document-versions` | Signed cursor and limit 1–100 (default 20), newest first; state, parser identity/config, unverified metadata, warnings, page/figure counts, created/completed times. |
| `GET /document-versions/{version_id}` | Same version metadata, including historical versions. |
| `GET /document-versions/{version_id}/pages/{page_number}` | One-based page, immutable text/status/warnings and PDF dimensions. Absent page returns 404. |
| `GET /document-versions/{version_id}/sections` | Ordered heuristic sections with page IDs/numbers and Unicode code-point spans. Zero-based inclusive start, exclusive end. |
| `GET /papers/{paper_id}/figures?document_version_id=...` | Required owned version from this paper; `offset` 0–200, `limit` 1–100 (default 50); items and nullable `next_offset`. Page/version references, caption candidate/offsets, nullable bounding box/method and private file URL. |
| `GET /figures/{figure_id}/file` | Owned PNG with private/no-store and nosniff headers. |

Every extraction route uses owner-scoped reads; foreign IDs are indistinguishable from absent IDs (404). The original remains downloadable on failure. A terminal partial result reaches 100% without claiming that OCR or missing structures succeeded. Parser configuration is fixed per job; changed runtime policy requires a new extraction rather than altering history. Heading/caption association correctness is not guaranteed by valid offsets.

For analysis, the fingerprint includes owner, paper/version, task, model/provider revisions, language, generation parameters, prompt/schema versions, and allowed fallback configuration. Ingestion uses owner, file hash, parser identity/version, and parser configuration. Idempotency replay returns the originally accepted response, while `GET /jobs/{job_id}` returns current progress.

Job states: `queued`, `running`, `completed`, `partially_completed`, `failed`. Stage values and deletion rules are defined in the data model. A failed job with unknown paid-request outcome requires acknowledgment before explicit retry. Ingestion retry creates a new document version; failed analysis retry creates a new job/report lineage without mutating the previous report.

## Contract implementation and checks

During foundation implementation, FastAPI generates OpenAPI from typed schemas; do not maintain a second hand-written executable specification. Generated documentation follows the [OpenAPI specification](https://spec.openapis.org/oas/v3.1.1.html). This document records behavior and scope; framework generation alone does not prove authorization or grounding.

Required implementation checks: authentication/CSRF rejection; cross-user access to every private route; invalid multipart data and file paths; duplicate upload races; stale ETags; idempotency replay/mismatch; unavailable broker recovery; duplicate task delivery; configuration revocation; citation mismatch; ambiguous provider timeout; partial report persistence; full browser workflow without paid credentials.
