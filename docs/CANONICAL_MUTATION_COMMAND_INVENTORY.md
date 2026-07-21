# Canonical Mutation Command Inventory

Status: implemented for the first production command boundary (schema migration v5).

## Authoritative paths

| Domain | Previous entry points | Canonical commands | Concurrency source | Stale effect |
|---|---|---|---|---|
| Project metadata and lifecycle | project API, archive UI, import | `UpdateProjectMetadata`, `ArchiveProject`, `UnarchiveProject`, `ImportProjectArchive` | project state token | explicit none |
| Layer 0 brief | Form API, Plan extraction, assistant confirmation, publish API | `UpdateBriefDraft`, `AppendBriefPlanTurn`, `PublishBrief` | canonical brief state token | descendant pillars declared deferred |
| Layer 1 pillars | manual add, node API, bulk UI, assistant confirmation | create, edit, keep, cut, prioritize, rename, and merge pillar commands | pillar state token; source and target tokens for merge | descendant features declared deferred when applicable |
| Layer 2 graph | create/edit API, review API, bulk UI, assistant confirmation, overlap decisions | create, edit, keep, cut, approve, rename, merge, bulk review, and relationship commands | feature state token; both endpoint tokens for graph edges | Layer 3 reconciliation declared deferred |
| Layer 3 revisions | generation job, edit/review API, candidate apply/reject/restore | generate candidate, edit/review active revision, accept, partially accept, reject, restore | active immutable revision ID | explicit none; revision service owns freshness |
| Critic findings | finding resolution API | resolve, dismiss, and reopen finding commands | finding state token | explicit none |
| Overlap verdicts | overlap review API | request overlap review and resolve verdict | verdict plus current artifact hashes | Layer 3 reconciliation declared deferred for Layer 2 graph changes |
| Durable workflows | generation/research API, assistant confirmation, Layer 3 worker | request Layer 1/2/3 generation, research, overlap review; generate Layer 3 candidate | idempotency key and source gates | explicit none |

All listed transports call `CommandService.handle`. The command service owns actor normalization, human-authority enforcement, optimistic concurrency, transaction scope, idempotency, typed results/errors, stale-effect declarations, and the `command_executions` audit row.

## Unit of work

`Database.unit_of_work()` supplies one ambient transaction. Existing database and domain-service calls reuse that connection, so canonical state, human-authority records, review records, current projections, and command audit completion commit or roll back together. PostgreSQL handlers lock authoritative rows with `SELECT ... FOR UPDATE`; SQLite uses `BEGIN IMMEDIATE`.

The v5 `command_executions` table stores command type, target, normalized actor/origin, idempotency key, request fingerprint, input, typed result, stale effects, and timestamps. `(project_id, idempotency_key)` is unique. Repeating the same request returns the stored result; reusing the key with different input is a conflict.

## State-transition rules

- Model and system actors cannot invoke human-only decisions. A confirmed assistant proposal remains a human actor with `assistant_confirmed` origin.
- Existing authoritative artifacts require an expected state token. Stale writes return a typed conflict with the expected token, current token, artifact, and reload recovery.
- Merged pillars and features are terminal for edit/review commands. Merge targets must be distinct, active artifacts in the same project.
- Archived projects are read-only except for lifecycle commands explicitly allowed by the lifecycle guard.
- Layer 3 candidate acceptance, partial acceptance, rejection, restoration, and human edits retain the immutable revision rules introduced in migrations v2-v3.
- Finding and overlap decisions validate their current durable state before applying side effects.

## Deliberate boundaries and exceptions

- Project creation is a bootstrap orchestration: allocating the project and default settings precedes the first project-scoped brief command, but all three writes share one ambient transaction. The command ledger has a project foreign key, so it cannot precede project allocation.
- Portable archive import remains a bulk importer because it allocates and remaps a new project internally. It is exposed as a typed import command with a trusted import actor; the archive importer retains its own all-or-nothing transaction and lifecycle warnings.
- Clone and purge retain the existing bulk lifecycle services. Clone creates a new identity graph; purge requires its existing explicit confirmation token and two-phase cleanup contract.
- Workspace preferences, model/settings administration, assistant transcripts/proposal status, job progress, telemetry, and supporting research evidence are operational or supporting records rather than authoritative Layer 0-3 product artifacts. They retain their dedicated services.
- Exports and diagnostic bundles write files after read-only snapshot assembly and are not database mutation commands.

These are explicit boundaries, not alternate ways to mutate canonical briefs, pillars, features, Layer 3 revisions, findings, or overlap decisions.
