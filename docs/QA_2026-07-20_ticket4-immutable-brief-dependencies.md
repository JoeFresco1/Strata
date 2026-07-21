# Ticket 4 QA — Immutable Brief Revisions and Dependency Staleness

## Verdict

Ticket 4 is production-safe for the implemented Layer 0–3 boundary. Published brief payloads are immutable, publication and stale propagation are atomic, derived artifacts retain content and human authority, Layer 3 stays non-destructive, and clearly stale/mixed Layer 3 exports are blocked.

## Schema and migration

Migration v6 adds `brief_heads`, `brief_revisions`, `artifact_dependencies`, `artifact_freshness_states`, and `artifact_stale_transitions`. It backfills the current brief as an exact revision and labels descendant lineage inferred unless historic source identity can be proved. PostgreSQL enforces head/revision ownership, unique revision numbering, published-content immutability, valid state/kind values, dependency ownership, duplicate prevention, and orphan cleanup.

Test fixture lineage counts:

- New exact Layer 1→2→3 fixture: exact 6, inferred 0, unknown 0.
- Live v5 legacy brief plus pillar fixture: exact 0, inferred 1, unknown 0.

## Command and state validation

Validated:

- editing after publication creates a separate draft revision;
- prior publications remain readable and unchanged;
- identical publication does not create duplicate revisions;
- stale expected state and concurrent publication produce typed conflicts without lost updates;
- publication marks only dependency-linked descendants stale;
- direct/transitive/already-stale command reports are durable and idempotent;
- Layer 1/2 review state, Layer 3 approval, human fields, and active revisions are preserved;
- feature edits stale only their Layer 3 branch;
- scope contracts, coverage matrices, and research assessments are marked stale without content rewrites;
- restoration copies source lineage and recalculates freshness;
- injected publication failure rolls back the revision head, stale projections/history, and command audit;
- archive, clone, import, purge, cross-project rejection, and orphan cleanup preserve integrity;
- the shared export validator detects stale, missing, superseded, and mixed lineage.

## Verification results

- Complete backend discovery: 176 discovered; 171 passed; 5 live-PostgreSQL-gated tests skipped in this pass.
- Live PostgreSQL 18 matrix: 5 passed, including realistic v5→v6 migration, immutability/ownership constraints, concurrency, rollback, lifecycle, and cleanup.
- Focused Ticket 4 unit matrix: 12 passed.
- Frontend cache tests: 9 passed.
- Frontend production build: passed (358 modules transformed).
- Python compileall: passed.
- Git whitespace validation: passed; only existing LF→CRLF checkout warnings were reported.
- Disposable PostgreSQL database cleanup: passed; zero matching databases remained.

## Remaining limitations

- Layer 1 pillars and Layer 2 features still use deterministic content tokens rather than dedicated immutable revision tables.
- Existing legacy descendants are inferred when historic lineage was not stored; migration does not invent exact history.
- Negative memory remains human-authority state and uses its existing semantic fingerprint rather than freshness transitions.
- Overlap data and assistant documents retain their existing lazy content-hash invalidation.
- Export freshness is validated at export time; export files do not yet have durable manifest rows.
- The complete specification compiler and checkpointed worker remain out of scope.
