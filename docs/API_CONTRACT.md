# Initial REST API contract

Status: design, version 0.1; the two health endpoints are implemented. All other resource endpoints remain planned. Generated runtime documentation is available at `/api/docs` through the frontend.
All resource routes below are relative to `/api/v1`.
Related: [architecture](ARCHITECTURE.md), [data model](DATA_MODEL.md).

## Shared behavior

- JSON uses snake_case; IDs are UUIDs; timestamps are UTC RFC 3339. Unknown fields in mutation payloads are rejected.
- Authentication uses an opaque HttpOnly cookie. Non-login mutations require `X-CSRF-Token`; login requires a trusted Origin and JSON. Provisioning is CLI-only.
- Missing resources and resources owned by another user both return 404. Invalid authentication returns 401; policy/capability restrictions for an owned resource return 403 or 422 as specified.
- Paginated responses use `{items, next_cursor}`. `limit` defaults to 20, maximum 100. Opaque cursors validate scope, filters, sort, and tie-breaking ID; malformed cursors return 422.
- List order defaults to descending creation time, then descending ID. Paper lists support bounded `q`, `project_id`, `tag`, and `processing_state`; project lists support `archived`.
- Mutable metadata/configuration reads return an ETag derived from revision. PATCH/PUT/DELETE require `If-Match` for existing mutable projects, papers, providers, models, and routing settings: absent returns 428, stale returns 412. Job/report/file reads are not mutable configuration.
- `Idempotency-Key` is required for upload, analysis creation, and retry creation. Scope is owner + operation; retain for at least 24 hours. Same key and canonical payload/hash replays its original status/body; different payload returns 409. An in-progress key returns 409 with a retry hint.
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
| `POST /papers/upload` | Multipart `file`, optional `project_id`; idempotency key | 201 `UploadRead` + Location for new paper; 200 same-owner duplicate, no new analysis |
| `GET /papers` | Pagination and documented filters | 200 paginated `PaperRead` |
| `GET /papers/{paper_id}` | Owned ID | 200 `PaperRead` + ETag |
| `PATCH /papers/{paper_id}` | `PaperPatch`, If-Match | 200 `PaperRead`; metadata correction, tags, project membership, privacy |
| `DELETE /papers/{paper_id}` | If-Match | 204 after database deletion; 409 if active work; storage cleanup follows durably |
| `GET /papers/{paper_id}/file` | Owned paper | 200 private PDF, supports byte ranges (206); no storage path; `Cache-Control: private, no-store` |
| `GET /papers/{paper_id}/document-versions` | Pagination | 200 version metadata including parse state/warnings |
| `GET /papers/{paper_id}/figures` | `document_version_id`, pagination | 200 paginated `FigureRead` |
| `GET /figures/{figure_id}/file` | Owned figure | 200 private image; safe content type and no-store |
| `POST /papers/{paper_id}/analyses` | `AnalysisCreate`, idempotency key | 202 `JobRead` + Location; 409 if not parsed or equivalent active work; 403 if external processing forbidden |
| `GET /jobs/{job_id}` | Owned ID | 200 `JobRead`; initial UI polls with bounded backoff |
| `POST /jobs/{job_id}/retry` | `RetryRequest`, idempotency key | 202 new `JobRead`; 409 if state not retryable; 422 if unknown-outcome acknowledgment missing |
| `GET /papers/{paper_id}/analyses` | Pagination | 200 paginated `AnalysisSummary` |
| `GET /analyses/{analysis_id}` | Owned ID | 200 `AnalysisRead`, immutable saved report |
| `GET /evidence/{evidence_id}` | Owned ID | 200 `EvidenceRead`; source file route and page reference |
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
| `DocumentVersionRead` | `id`, `paper_id`, `state`, nullable parser name/version, `warnings`, `created_at`, nullable `completed_at` |
| `FigureRead` | `id`, `paper_id`, `document_version_id`, `page_number`, nullable caption and bounding box, `file_url` (owned relative API route), `extraction_method` |
| `AnalysisCreate` | `document_version_id: UUID`, `model_configuration_id?: UUID`, `language` (enum: `en`, `fa`), `parameters?: object` validated against provider/model, `consent_provider_ids: UUID[]` matching the resolved provider/fallbacks |
| `RetryRequest` | `acknowledge_possible_duplicate_cost?: bool` (default false); unchanged snapshot must still be valid or submit a new analysis instead |
| `JobRead` | `id`, `paper_id`, nullable `document_version_id`, `kind`, `state`, nullable `stage`, `progress_percent`, `attempt`, nullable `retry_of_job_id`, nullable `analysis_id`, sanitized nullable `error`, nullable `retry_requirement`, timestamps |
| `AnalysisSummary` | `id`, `paper_id`, `document_version_id`, `state`, `language`, `execution_mode` (enum: `live`, `mock`), safe model/provider names, `created_at` |
| `AnalysisRead` | `AnalysisSummary` fields + safe `configuration_snapshot`, `schema_version`, `sections: ReportSectionRead[]` |
| `ReportSectionRead` | `kind`, `status` (enum: `available`, `unavailable`, `failed`), nullable `reason_code`, validated `payload`, `claims: ClaimRead[]` |
| `ClaimRead` | `id`, `text`, `claim_kind` (enum: `source_statement`, `supported_inference`, `ai_suggestion`), nullable `confidence_note`, `evidence_ids: UUID[]` |
| `EvidenceRead` | `id`, `paper_id`, `document_version_id`, `page_number`, nullable `section_heading`, `start_offset`, `end_offset`, `quote`, `source_file_url` |
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

Upload returns after private storage and durable database commit; parsing runs asynchronously. Starting analysis requires a usable `ready` or `partially_ready` document version and freezes its configuration. A new idempotency key permits intentional re-analysis after previous work has terminated; equivalent active work returns 409.

For analysis, the fingerprint includes owner, paper/version, task, model/provider revisions, language, generation parameters, prompt/schema versions, and allowed fallback configuration. Ingestion uses owner, file hash, parser identity/version, and parser configuration. Idempotency replay returns the originally accepted response, while `GET /jobs/{job_id}` returns current progress.

Job states: `queued`, `running`, `completed`, `partially_completed`, `failed`. Stage values and deletion rules are defined in the data model. A failed job with unknown paid-request outcome requires acknowledgment before explicit retry. Ingestion retry creates a new document version; failed analysis retry creates a new job/report lineage without mutating the previous report.

## Contract implementation and checks

During foundation implementation, FastAPI generates OpenAPI from typed schemas; do not maintain a second hand-written executable specification. Generated documentation follows the [OpenAPI specification](https://spec.openapis.org/oas/v3.1.1.html). This document records behavior and scope; framework generation alone does not prove authorization or grounding.

Required implementation checks: authentication/CSRF rejection; cross-user access to every private route; invalid multipart data and file paths; duplicate upload races; stale ETags; idempotency replay/mismatch; unavailable broker recovery; duplicate task delivery; configuration revocation; citation mismatch; ambiguous provider timeout; partial report persistence; full browser workflow without paid credentials.
