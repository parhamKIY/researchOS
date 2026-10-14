# Initial relational data model

Status: migrations through `0007_system_llm` implement identity, private papers/extraction/jobs, owned provider/model/routing/usage records, administrator roles and singleton system LLM settings. Analysis/report/evidence tables remain planned.

`User.is_admin` defaults to false; role creation/elevation uses trusted local CLI commands. `User.revision` guards status mutations. Administrator access does not bypass paper ownership. `SystemLLMSettings` has a database-constrained singleton ID 1, positive revision and FK to the active `SystemProviderCandidate`. Candidates preserve safe protocol/URL/model/parameter/check/usage snapshots and nullable administrator attribution. States are `testing`, `failed`, `applied`, `superseded`, `stale`. Keys use a separate authenticated encryption context bound to immutable candidate ID, and are erased on unsuccessful tests, supersession or interrupted-probe recovery. Atomic activation compares the singleton revision after external I/O. Existing personal records are preserved.

Stage 4 stores encrypted credentials on the provider connection, with authenticated owner/provider binding. Provider/model composite keys constrain model ownership and usage records to their exact provider/model pair. Providers are soft-deleted and credentials removed; models can be disabled and reenabled. Usage keeps safe name snapshots after configuration changes, never prompts, raw outputs or keys. Routing settings initialize lazily with revision 1; an ETag guards atomic full replacement. Capabilities remain manually declared. Costs/token counts are nullable, and mock observations are explicitly synthetic. The initial usage table records connectivity attempts; job/report-linked billing and budget enforcement remain later work.
Related: [architecture](ARCHITECTURE.md), [API contract](API_CONTRACT.md).

User paper metadata remains a bounded subset: nullable title, privacy policy, revision and timestamps. Parsed PDF-info metadata and DOI candidates are stored separately on each document version, without overwriting the title. Latest version/job IDs are derived in reads. A paper has one immutable original file. Cleanup rows represent pending work implicitly and are removed after successful deletion. The broader table descriptions below include planned fields; they are not a claim that every column exists today.

Implemented ingestion details: composite foreign keys constrain source files to the same owner/paper and pages, section spans and figures to the same owner/version. Version states are `queued`, `processing`, `ready`, `partially_ready`, `failed`. Page text states are `available`, `no_text`, `failed`. Sections store heuristic heading labels with spans into immutable page text; figures store raster PNG keys, nullable caption offsets/association method and top-origin PDF-point bounding boxes. Unknown metadata stays nullable/unverified. Jobs hold a frozen file hash/parser/configuration snapshot, guarded lease, dispatch deadline and safe error code. A partial unique index prevents equivalent active work. Manual retry creates a new version and job lineage; lease recovery reuses the unfinished version. Active jobs block paper deletion. Deletion queues all original/image keys before cascading database records.

## Conventions and integrity

- UUID primary keys; UTC timezone-aware timestamps. Mutable configuration/resources use `created_at`, `updated_at`, and integer `revision` for optimistic concurrency.
- `owner_id` is mandatory on private roots and descendants. Private parent tables expose `UNIQUE(owner_id, id)`; descendant relations use composite foreign keys, not merely a global ID.
- Version-scoped evidence relations additionally include `document_version_id` so a report cannot cite another parsed version or paper. Composite unique targets are declared before foreign keys.
- A paper is an owner-scoped library item and may belong to multiple projects through a join table. It is not owned by one project.
- File bytes and images live outside PostgreSQL. Storage keys are generated opaque identifiers; public URLs and user-supplied paths are not persisted as storage locations.
- Relational ownership, version, state, and evidence fields are typed columns. JSONB is reserved for validated snapshots, parser warnings, generation parameters, and structured section payloads.
- Use database constraints for uniqueness and referential integrity, and service authorization for every access. Database checks are defense in depth, not a replacement for scoped queries.
- The claim's `section_id` references its report section; evidence's optional `section_id` references an extracted paper section. Composite keys also enforce that claims and report sections belong to the same report, not just the same owner.
- Project membership changes increment each affected paper's revision, including project deletion, so its ETag covers the returned `project_ids`. Perform these updates in the membership transaction.

PostgreSQL supports the required [unique, check, and composite foreign-key constraints](https://www.postgresql.org/docs/current/ddl-constraints.html). Migrations must define and exercise these constraints against PostgreSQL.

## Initial tables

| Table | Important fields and relationships | Rules |
|---|---|---|
| `users` | `id`, `email_normalized`, `password_hash`, `is_active` | Unique normalized email; locally provisioned account |
| `auth_sessions` | `id`, `owner_id`, `token_hash`, `csrf_token_hash`, `expires_at`, `revoked_at` | Unique token hash; expiry checked on every request |
| `research_projects` | `id`, `owner_id`, `name`, `description`, `archived_at`, `revision` | Archive is reversible; distinct projects may share a name |
| `papers` | `id`, `owner_id`, `title`, `authors`, `publication_year`, `venue`, `doi_normalized`, `abstract`, `metadata_source`, `external_processing_allowed` | Title may be unknown; metadata has source/uncertainty; external processing defaults off |
| `paper_projects` | `owner_id`, `paper_id`, `project_id` | Composite primary key; both foreign keys enforce the same owner |
| `paper_tags` | `owner_id`, `paper_id`, `tag_normalized`, `label` | Unique normalized tag per paper; bounded user-provided labels |
| `paper_files` | `id`, `owner_id`, `paper_id`, `sha256`, `storage_key`, `original_name`, `byte_size`, `media_type` | Unique `(owner_id, sha256)` and storage key; positive size; MVP original file is immutable |
| `storage_cleanup_tasks` | `id`, `owner_id`, `storage_key`, `state`, `attempt`, `retry_after`, sanitized `error_code` | Created before file metadata deletion; unique pending storage key; no source text |
| `document_versions` | `id`, `owner_id`, `paper_id`, `file_id`, `parser_name`, `parser_version`, `parser_config`, `state`, `warnings` | Each parse/reparse has its own version; source file belongs to same paper |
| `document_pages` | `id`, `owner_id`, `document_version_id`, `page_number`, `text`, `width`, `height` | One-based page number; unique page per version; immutable after publication |
| `paper_sections` | `id`, `owner_id`, `document_version_id`, `kind`, `heading`, `ordinal` | Kind may be unknown; content comes from source spans, not an unrelated text copy |
| `section_spans` | `owner_id`, `document_version_id`, `section_id`, `page_id`, `start_offset`, `end_offset` | Associates sections spanning multiple pages with exact page text ranges |
| `paper_figures` | `id`, `owner_id`, `document_version_id`, `page_id`, `storage_key`, `caption`, `bounding_box`, `extraction_method` | Caption nullable; referenced page belongs to the same version |
| `provider_connections` | `id`, `owner_id`, `adapter`, `display_name`, `encrypted_credential`, `key_version`, `credential_revision`, `enabled`, `revision` | Ciphertext never serialized; no arbitrary endpoint in MVP; deletion disables and clears credentials |
| `model_configurations` | `id`, `owner_id`, `provider_id`, `model_name`, `capabilities`, `capability_source`, `parameters`, `revision`, `enabled` | Provider has same owner; capabilities are validated/manual, not inferred from name |
| `model_routing_settings` | `owner_id`, `revision`, timestamps | One aggregate settings row per user, including initially empty settings; locks atomic replacements |
| `model_routing_rules` | `owner_id`, `task`, `primary_model_id`, `fallback_model_id`, `allowed_provider_ids` | One rule per task; references owner settings; fallbacks are opt-in and same-owner; model capability checked |
| `processing_jobs` | `id`, `owner_id`, `paper_id`, `document_version_id`, `kind`, `state`, `stage`, `progress_percent`, `snapshot`, `fingerprint`, `attempt`, `dispatch_after`, `lease_token`, `lease_expires_at`, `heartbeat_at`, `error_code` | Durable work and progress; snapshot excludes keys; fingerprint identifies identical active work |
| `idempotency_records` | `id`, `owner_id`, `operation`, `key`, `request_hash`, `response_status`, `response_body`, `expires_at` | Unique `(owner_id, operation, key)`; responses contain no secrets |
| `analysis_reports` | `id`, `owner_id`, `paper_id`, `document_version_id`, `job_id`, `language`, `schema_version`, `configuration_snapshot`, `execution_mode`, `state` | Unique job; immutable report; `execution_mode` is `live` or `mock` |
| `report_sections` | `id`, `owner_id`, `report_id`, `kind`, `status`, `reason_code`, `payload` | Unique kind per report; partial/unavailable sections retained explicitly |
| `research_claims` | `id`, `owner_id`, `report_id`, `section_id`, `document_version_id`, `text`, `claim_kind`, `confidence_note`, `extraction_method` | Kind: `source_statement`, `supported_inference`, or `ai_suggestion`; version matches report |
| `supporting_evidence` | `id`, `owner_id`, `document_version_id`, `page_id`, `section_id`, `start_offset`, `end_offset`, `quote` | Source offsets and exact quote verified against immutable page text; section optional |
| `claim_evidence` | `owner_id`, `document_version_id`, `claim_id`, `evidence_id` | Composite keys forbid linking claims to another owner's or another version's evidence |
| `ai_usage_records` | `id`, `owner_id`, `job_id`, `provider_id`, `model_configuration_id`, `task`, `attempt`, `request_fingerprint`, `state`, `provider_request_id`, `input_tokens`, `output_tokens`, `cost_amount`, `currency`, `cost_source`, `latency_ms` | One record per request attempt; nullable usage/cost; safe model/provider snapshot retained for history |

## Required indexes and checks

- Listing: `(owner_id, created_at DESC, id DESC)` on projects, papers, jobs, and reports; appropriate paper/project foreign-key indexes.
- Owner-scoped deduplication: unique file hash; partial unique `(owner_id, doi_normalized)` when a DOI is present. Metadata-only similarities produce suggestions, not automatic merging.
- Active jobs: partial unique `(owner_id, fingerprint)` while state is `queued` or `running`; worker claim updates state/lease atomically.
- Dispatch/recovery: indexes on `(state, dispatch_after)` and active lease expiry. A heartbeat cannot change terminal work back to running.
- Source ranges: `0 <= start_offset < end_offset`; page text bounds and exact quotes checked in the service transaction. Offsets use Unicode code points in stored normalized page text.
- Job progress: integer 0–100; only terminal successful/partial jobs reach 100. State and stage are separate: retry may revisit a stage without inventing completion progress.
- Nonnegative token/cost/latency counts when present. Unknown values remain NULL. Usage state includes `started`, `succeeded`, `failed`, and `outcome_unknown`.
- Provider-specific parameters are schema validated. Stored credential ciphertext uses authenticated encryption with an application-managed key ID for later rotation.
- Index foreign keys where deletion/joins need them; do not index every JSON field preemptively.

## Version and configuration rules

`DocumentVersion` identifies one immutable extraction result. Its source is a specific immutable `PaperFile`. New parsing creates another version; historical reports never switch to newer text.

Document version states are `queued`, `processing`, `ready`, `partially_ready`, and `failed`. Analysis may consume `ready` or `partially_ready` versions only when enough usable text exists; extraction warnings remain visible. Report states are `completed` or `partially_completed`; failed analysis without usable sections has a failed job and no successful report.

Before enqueueing an analysis, the server resolves the explicit model or the configured routing rule, validates privacy/capabilities, and freezes safe provider/model names, model configuration revision, credential revision, parameters, prompt/schema versions, language, allowed fallback providers, and document version. Secrets are not copied into the snapshot or broker message.

A credential replacement/disable invalidates queued work referring to its previous revision. Disabling a model also prevents queued use; ordinary parameter edits do not rewrite frozen job parameters. The user can submit a new job explicitly. Provider/model soft deletion preserves historical names/snapshots and usage; revoked ciphertext is removed immediately.

## Job lifecycle

```text
queued -> running -> completed
                  -> partially_completed
                  -> failed
```

Safe retry creates a new execution attempt of the same nonterminal job and retains checkpoints. A user retry after terminal failure creates a new job linked by `retry_of_job_id`. Unknown provider outcome is represented by `failed` plus `error_code=provider_outcome_unknown` and an explicit retry requirement.

Stages: `parsing`, `extracting_metadata`, `extracting_figures`, `preparing_context`, `running_analysis`, `validating_output`, `persisting_results`. Jobs also include `created_at`, `started_at`, and `finished_at`. Ingestion can complete without an AI call; analysis requires a published usable document version.

## Deletion and retention

- Project deletion removes memberships, not library papers; archive only hides the project by default.
- Paper deletion requires no queued/running job. Return 409 otherwise. Delete report/evidence/version/membership records transactionally and leave a minimal owner-scoped cleanup task for private storage keys; cleanup retries are idempotent.
- Storage cleanup keys are internal, never exposed in API responses. A reconciliation task removes old unreferenced temporary uploads and retries pending file cleanup.
- Usage/financial history may survive paper deletion with nullable deleted-resource references and safe configuration metadata. It must not retain source text or credentials.
- User account deletion is not exposed in the initial API. Before public hosting, define export/retention and full private-data removal policies.

## Later additions

Paper tables and table-cell evidence, document chunks and embedding spaces, conversations/messages, saved findings/ideas, discovery caches, and budget policies are added through later migrations. No unused vector columns, training tables, or public-sharing model are required for the foundation.

## Review required during migrations

Verify cross-owner and cross-document-version relations are rejected; deduplication races produce one record; failed uploads do not leak files; concurrent job claims yield one lease; deletion cannot race an active claim; immutable evidence survives reparse; rotated/revoked keys are never used by queued work.
