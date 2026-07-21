# Layer 3 PostgreSQL Revision Validation — 2026-07-20

## Verdict

The Layer 3 immutable-revision migration train is safe for the current STRATA PostgreSQL database when versions 2 and 3 are deployed together. Migration v2 preserves and backfills legacy Layer 3 projections. Migration v3 adds the database-enforced ownership, state, and active-head integrity constraints exposed as missing during live validation.

The original v2 implementation should not be deployed alone: live PostgreSQL testing found runtime serialization, fresh-database bootstrap, lifecycle import/purge, and relational-integrity defects. All discovered defects were corrected and revalidated.

## Environment

- PostgreSQL: 18.0, 64-bit Windows build
- Driver: psycopg through the repository virtual environment
- Database: uniquely named disposable `strata_l3_revision_test_*` databases on the repo-local PostgreSQL server
- Cleanup: every disposable database was dropped with `WITH (FORCE)` after its run; a catalog check found no remaining validation databases

## Migration Commands and Results

The focused integration harness performed the realistic upgrade sequence:

1. Create a fresh disposable PostgreSQL database.
2. Initialize and seed realistic legacy projects.
3. Remove all v2 tables and projection revision columns to recreate pre-v2 state.
4. Record schema migration v1.
5. Reopen with current STRATA schema initialization.
6. Run `apply_migrations(db)` and verify `[2, 3]`.
7. Reopen the database and verify persisted revision state.

Current database commands:

```powershell
.\.venv\Scripts\python.exe -m strata.migrations upgrade
.\.venv\Scripts\python.exe -m strata.migrations status
```

Result: no pending versions; current and latest schema version are both 3.

## Legacy Upgrade Coverage

The pre-v2 fixture included:

- a project with no Layer 3 expansion;
- a project with one approved expansion;
- a project with two feature expansions;
- approved and needs-review projection states;
- human-edited group and option content;
- an existing legacy edit action used to recover field ownership.

After migration:

- projects without Layer 3 data had no artificial heads or revisions;
- every legacy expansion became revision 1;
- every migrated projection received its revision ID and number;
- approved and needs-review states were preserved;
- human-owned nested fields were preserved and marked as human-owned;
- the complete current read projection was byte-for-value equivalent for all pre-v2 fields.

## Schema and Integrity Verification

Created and inspected:

- `layer3_expansion_heads`
- `layer3_expansion_revisions`
- `layer3_expansion_revision_states`
- `layer3_revision_actions`

Verified constraints and indexes include:

- one head per `(project_id, feature_id)`;
- unique revision number per logical expansion;
- unique idempotency request ID;
- foreign-key ownership from revisions to their logical head and project;
- foreign-key ownership from states to the correct logical revision;
- foreign-key ownership from actions to the correct head, project, and revision;
- active projection and active head pointers restricted to revisions of the same logical expansion;
- allowed workflow, review, and freshness state checks;
- candidate/rejected/partial-apply state consistency checks;
- one deferred active slot per logical expansion;
- deferred constraint triggers proving the head points to its sole active revision at commit;
- positive revision-number and next-revision-number checks;
- project, feature, revision, state, action, and projection cascade behavior;
- indexes for revision history lookup and action history lookup.

Direct negative tests proved that orphan revisions, duplicate revision numbers, and inconsistent candidate review states are rejected by PostgreSQL.

## Runtime Scenarios

The focused PostgreSQL test exercised:

- candidate creation without projection mutation;
- full candidate acceptance;
- partial acceptance of only `feature_intent`;
- candidate rejection;
- restoration as a new revision;
- idempotent repeated full acceptance;
- HTTP 409 after a concurrent active edit;
- injected rollback after verify, accept, supersede, projection, and audit stages;
- restart persistence through a new `Database` instance;
- two simultaneous candidate creations receiving consecutive unique revision numbers;
- two simultaneous acceptance attempts against one expected active revision, with exactly one success and one conflict;
- exactly one active state after concurrent acceptance;
- approved Layer 3 export;
- project archive/unarchive;
- project clone with revision history and pending candidates;
- full archive export/import with revision-count preservation;
- project purge with complete revision/head/action cleanup.

## PostgreSQL Defects Found and Corrected

1. Fresh databases registered pgvector before creating the extension. Connection bootstrap now tolerates the absent type only during schema initialization.
2. JSONB audit snapshots failed on native PostgreSQL timestamps. Revision audits now recursively normalize timestamps before persistence.
3. V2 lacked cross-table foreign keys, state checks, sole-active enforcement, and orphan prevention. Migration v3 adds the required constraints and deferred consistency triggers.
4. Archive import attempted to write PostgreSQL generated columns. Import column discovery now excludes generated columns.
5. Cloned/imported revision audit rows reused globally unique idempotency keys. Imported actions now receive fresh request IDs.
6. Archive import and project purge committed table rows independently, conflicting with deferred revision invariants and permitting partial lifecycle writes. Both operations now mutate project rows atomically.

## Test Results

- Focused PostgreSQL integration: `1 passed, 5 subtests passed`
- Complete backend suite: `128 passed, 8 subtests passed`
- Python compilation: passed for `strata` and `tests`
- Known non-blocking warning: Starlette's TestClient emits its existing `httpx` deprecation warning

## Production Database State

The current `specforge` database is PostgreSQL 18.0 and reports migrations 1, 2, and 3 applied. It contained zero Layer 3 projections, heads, revisions, or revision actions during the validation check, and all required v3 constraints were present. No production project data was created or deleted by the disposable integration harness.
