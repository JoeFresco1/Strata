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

The application can create and work projects, but it lacks complete lifecycle
operations.

Completion requires:

- rename and edit project metadata;
- delete with explicit confirmation;
- duplicate or create from a project template;
- portable project archive export and import;
- clear handling for imported schema versions and missing model profiles.

### 3. Backup, restore, and data ownership

JSON exports are not a complete database backup.

PostgreSQL backup and restore commands are now documented for Docker Compose
and native installs, with a restore verification step.

Completion requires:

- one-click or scripted backup for Docker installations;
- retention and deletion behavior for telemetry, research content, exports, and
  assistant history;
- project-level purge tools.

### 4. Full background-work visibility

The Analytics surface now reports model calls, dependency health, and one
unified queue for research, generation, assistant, replay, diagnostics, and
Layer 3 audit jobs. The queue shows status, current step, progress, recent
failure context, basic failure grouping by model-provider, database, crawler,
parser, and application categories, plus cancel/retry actions.

### 5. Diagnostics completeness

The diagnostics bundle now runs as a durable job and contains a deterministic
manifest, schema or migration status, dependency-health snapshots, project model
settings, telemetry, platform jobs, and research jobs. It is closer to the
intended one-click support bundle, but still not complete.

Completion requires:

- sanitized application and worker logs;
- recent errors and traces;
- configurable redaction preview;
- fuller deterministic bundle versioning.

### 6. Layer 3 competitive intelligence

Competitive intelligence can now be disabled project-wide. When enabled, Layer
3 generation still does not consume feature-level competitor evidence or
produce cited competitive positioning.

Completion requires an optional, evidence-grounded Layer 3 analysis covering:

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

Completion requires:

- a fresh disposable install;
- first-run setup;
- project creation through Layer 3;
- restart during active work;
- cancel/retry paths;
- backup/restore;
- archive export/import;
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
