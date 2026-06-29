# Strata Platform Completion Audit

Date: 2026-06-27

Status: pre-release platform; packaging exists, product completion remains open.

## What is already substantial

Strata has working Layer 0 through Layer 3 workflows, durable PostgreSQL state,
project-scoped model routing, competitive-intelligence controls, a project
assistant, telemetry, exports, a self-hosted runtime, and automated regression
coverage. The remaining work is not a blank platform build. It is the set of
product and reliability boundaries required before calling the platform
finished.

## Release blockers

### 1. Unified durable job control

Implemented on 2026-06-27. Strata now has a shared `platform_jobs` control
plane across research, generation, assistant execution, telemetry replay,
diagnostics export, and Layer 3 pressure/coverage audits.

Current behavior:

- one job vocabulary across research, generation, assistant, replay,
  diagnostics, and audits;
- queue, running, completed, failed, cancelled, and interrupted states;
- progress and current-step reporting;
- user cancellation and retry through project job routes;
- in-process bounded execution and active duplicate-job prevention;
- restart recovery that marks interrupted jobs retryable without deleting
  domain provenance.

### 2. Project lifecycle management

Implemented on 2026-06-28. Strata now has active/archived project library
filters, project metadata editing, archive/unarchive, read-only archived
inspection, deep clone, portable project archive export/import, and an
admin-only irreversible purge command.

Current behavior:

- `GET /api/projects` supports lifecycle state, search, and server-backed sort;
- project metadata edits update library name and summary without rewriting the
  canonical Layer 0 brief;
- archived projects remain readable/exportable/cloneable but reject canonical
  project writes until unarchived;
- clone creates a working copy with clone lineage while excluding telemetry,
  assistant history, active job state, workspace selection, and disk exports;
- portable archive export/import creates a new project ID and preserves
  project-scoped product state, telemetry, assistant history, research, Layer 2,
  and Layer 3 state;
- imported unavailable local model paths are normalized with warnings;
- irreversible purge is restricted to the admin CLI with an explicit
  confirmation token.

### 3. Backup, restore, and data ownership

JSON exports are not a complete database backup.

PostgreSQL backup and restore commands are documented for Docker Compose and
native installs. Docker installations now have scripted backup and restore
wrappers, timestamped backup metadata sidecars, backup inspection, and a live
restore verification command.

Current behavior:

- Docker backup scripts create compressed PostgreSQL dumps under `backups/`;
- restore scripts require an explicit `RESTORE-<backup filename>` token before
  replacing the database;
- `python -m strata.backup verify-live` checks migration status, project
  readability, pgvector, telemetry, research, assistant tables, and exports;
- project data ownership settings default to retain-until-explicit-deletion;
- admin cleanup can redact/delete telemetry, research content, assistant
  history, and matching export artifacts by configured or explicit retention;
- project purge has dry-run table/artifact previews and still requires the
  admin confirmation token for destructive deletion.

### 4. Full background-work visibility

The Analytics surface now reports model calls, dependency health, and one
unified queue for research, generation, assistant, replay, diagnostics, and
Layer 3 audit jobs. The queue shows status, current step, progress, recent
failure context, basic failure grouping by model-provider, database, crawler,
parser, and application categories, plus cancel/retry actions.

### 5. Diagnostics completeness

Implemented on 2026-06-28. The diagnostics bundle now runs as a durable job and
contains a version-2 deterministic manifest, schema or migration status,
dependency-health snapshots, project model settings, telemetry, platform jobs,
research jobs, sanitized runtime logs, recent errors, and recent traces.

Current behavior:

- diagnostics export accepts request-scoped inclusion and line-limit options;
- preview returns included sections, counts, warning metadata, redaction counts,
  and sample snippets without writing an export file;
- logs and support payloads redact bearer/basic tokens, API keys, database URLs,
  emails, local paths, and long secret-like values with stable labels;
- manifest includes `strata.diagnostics.bundle.v2`, generator version, sorted
  sections, warnings, redaction metadata, and a deterministic content hash.

### 6. Layer 3 competitive intelligence

Implemented on 2026-06-28. Competitive intelligence can be disabled
project-wide, and when enabled Layer 3 now supports a separate optional cited
competitive-analysis pass that reuses latest Layer 2 feature evidence instead
of blending competitor interpretation into the noncompetitive coverage-gap
audit.

Current behavior:

- parity requirements;
- differentiation opportunities;
- competitor patterns worth avoiding;
- product-positioning decisions;
- source citations and provenance;
- explicit separation from the noncompetitive coverage-gap audit.

### 7. First-run and provider onboarding

The first-run screen records one OpenAI-compatible endpoint, model name, and
embedding choice, offers simple local runtime presets, explains no-model
read-only behavior, then runs a basic post-save health check. Advanced provider
setup still remains in project and app settings.

Completion requires:

- endpoint validation with actionable errors;
- secure bearer-token entry that is never returned to the browser;
- context-window and output-limit checks;
- a model capability test before starting expensive workflows;
- tested verification for common local runtime presets.

### 8. End-to-end release QA

The product passed a fresh live QA pass on 2026-06-27 across core and release
surfaces after telemetry, self-hosting, first-run setup, competitive-intelligence
controls, and Layer 3 coverage-gap analysis landed. What remains incomplete is
the full release matrix rather than basic post-change coverage.

As of 2026-06-28, the repo now includes a reusable release matrix runbook in
`docs/RELEASE_QA_MATRIX.md`, a disposable native runner in
`scripts/run_release_qa_native.ps1`, and dedicated browser/API evidence probes
under `.tmp-playwright/`. A fresh native disposable run now exists in
`docs/QA_2026-06-28_release-matrix.md` and
`.runtime/release-qa/20260628-082739`. This blocker remains open until the
same report also includes native PostgreSQL backup/restore proof and a
separate Docker-capable run report.

Completion requires:

- a fresh disposable install;
- first-run setup;
- project creation through Layer 3;
- restart during active work;
- cancel/retry paths;
- backup/restore;
- archive export/import release validation;
- Docker and native installation checks;
- desktop and mobile browser QA.

## Important but not release-blocking

- Project templates and examples.
- Better onboarding copy and guided empty states.
- Prompt-catalog version history and rollback.
- Automatic update notifications.
- Optional plugin/provider architecture.
- Localization.
- Performance testing on larger projects.

## Definition of finished for the first public release

The first public release is ready when every release blocker above is either
implemented and verified or explicitly removed from the promised v0.1 scope.
Packaging alone does not satisfy this gate.
