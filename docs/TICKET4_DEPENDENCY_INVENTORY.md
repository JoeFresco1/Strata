# Ticket 4 Dependency Inventory

This inventory records STRATA's dependency behavior before the Ticket 4 schema change. It distinguishes canonical content from derived, operational, and diagnostic state and avoids claiming immutable lineage where the current database only stores mutable IDs or timestamps.

| Source | Derived artifact | Identifier currently stored | Immutable? | Current invalidation | Class | Ticket 4 treatment |
|---|---|---|---|---|---|---|
| Published Layer 0 brief | Layer 1 pillar (`nodes`) | Project association only; prompt-time brief content | No | None; a draft edit currently reports deferred descendants | Canonical | Add exact brief revision dependency and stale propagation |
| Published Layer 0 brief | Layer 2 feature (`layer2_features`) | Project association only; generation run references pillar IDs | No | None | Canonical | Add exact brief revision dependency |
| Layer 1 pillar | Layer 2 generation run/raw candidate/feature | `source_pillar_ids`, `pillar_id`, `owner_pillar_id` | No; pillar ID is logical and mutable | Research marker may be written on pillar; feature propagation is deferred | Operational/canonical | Use deterministic pillar content revision token; mark dependent features stale |
| Brief, pillar, Layer 2 feature | Layer 3 revision | `source_brief_revision`, `source_pillar_revision`, `source_layer2_feature_revision` | Brief/pillar values are currently ad hoc; feature timestamp is mutable-version token | Layer 3 read path recomputes fresh/stale from current tokens | Canonical revision | Replace brief value with exact revision ID; retain strongest pillar/feature token; persist dependencies and stale reasons |
| Pillar | Layer 2 scope contract (`project_memory`) | `scope_id=pillar_id` | No | Replaced/upserted by memory write | Derived | Track dependency and mark stale now |
| Pillar/features | Layer 2 coverage memory and matrix | Pillar/feature IDs and current payload | No | Recomputed by generation/research; no durable freshness history | Derived | Track dependencies and mark stale now |
| Human rejected feature | Layer 2 negative memory | Rejected feature ID/name/embedding | No exact source revision | Preserved indefinitely; semantic lookup remains active | Canonical human memory | Preserve; record source fingerprint where feasible, never erase on staleness |
| Brief/pillar/features | Research jobs, findings, sources, evidence | Project/scope/scope ID, job IDs, citations | Scope ID is mutable logical identity | Pillar payload may receive `research_stale`; reruns replace current scope data | Derived/operational | Add dependencies for assessments/evidence and mark stale now where target is known |
| Layer 1/2 text | Overlap findings, verdicts, clusters | Item IDs plus content hashes | Hash is immutable for one reading | Snapshot suppresses verdicts whose hashes no longer match | Diagnostic | Retain hash-based lazy invalidation; dependency rows deferred |
| Project artifacts | Assistant index documents | Source type/ID and `content_hash` | Hash is immutable for one document body | Indexer deletes/rebuilds on hash/key mismatch | Derived cache | Keep lazy fingerprint rebuild; never treat mismatched documents as current context |
| Canonical project state | Layer 2/3 exports | Payload assembled at request time; Layer 3 contains revision lineage | Only Layer 3 revision IDs are immutable | Approval gates only; no shared lineage coherence check | Derived output | Add shared freshness validator and block clearly stale/mixed Layer 3 exports |
| Project database rows | Archive/clone/import | Table rows and exported manifest | Mixed | Generic table copy/remap | Lifecycle | Include new revision/dependency/history tables; remap project-owned IDs safely |

## Current dependency paths

- Brief to Layer 1: generation and manual creation require `project_briefs.status = published`, but pillars do not retain which publication they used.
- Brief and pillar to Layer 2: generation reads the current published brief and current pillar text. Runs retain pillar IDs, not immutable pillar content revisions; canonical features retain only their owner pillar.
- Brief, pillar, and feature to Layer 3: immutable Layer 3 revision rows carry three source strings. Feature and pillar values are deterministic state/version tokens where supplied; the brief value is not backed by an immutable revision table.
- Scope contracts and coverage: both are derived from current pillar/feature text and are reused by later generation. Their current project-memory/matrix rows lack a freshness state and reason history.
- Research and evidence: scope IDs and research job IDs identify the target and run, while source text lineage is implicit. Pillar research uses a mutable `research_stale` marker.
- Negative memory: rejection decisions are human authority and must survive. Its embedding/name fingerprint can become diagnostically old but must not be automatically deleted or reversed.
- Overlap: hash comparison already gives safe lazy invalidation, so Ticket 4 need not redesign it.
- Assistant documents: content hashes already provide lazy cache invalidation. The index must rebuild on mismatch before use.
- Exports: Layer 3 export is the first practical enforcement point for a shared lineage/freshness validator.

## Design boundary

Ticket 4 will introduce only brief heads/revisions, narrow artifact dependencies, mutable freshness projections, and append-only stale transitions. Layer 1 and Layer 2 keep their current tables; their command state tokens serve as temporary content revisions until dedicated immutable revision models are justified. Review state, critic state, and freshness remain independent.

## Implemented schema (migration v6)

- `brief_heads`: one logical brief per project, current draft/publication pointers, monotonic revision counter, timestamps.
- `brief_revisions`: immutable normalized payload and content hash, revision number, origin/actor/command reference, lineage quality, publication and supersession timestamps.
- `artifact_dependencies`: narrow project-local source/dependent revision edges with dependency kind and exact/inferred/unknown quality.
- `artifact_freshness_states`: independent current/stale/superseded/unknown projection per artifact revision.
- `artifact_stale_transitions`: append-only before/after source replacement evidence, prior freshness, command, actor, origin, reason, and timestamp.

PostgreSQL enforces revision ownership, unique revision numbers, head-pointer ownership, valid states/kinds/lineage labels, duplicate prevention, published-content immutability, cross-project dependency validation, and cleanup triggers. SQLite retains application validation and cleanup triggers for local/test compatibility.

## Revision and state-transition model

Draft editing snapshots changed content into a new immutable draft revision and moves only the draft pointer. It does not alter the published pointer or stale descendants. Publishing selects the draft revision, or reselects the existing publication when hashes match; a changed publication supersedes the prior brief revision and atomically propagates staleness. Previous published content is never updated.

Freshness and review remain independent. Content-source changes transition matching dependent revisions from current to stale and append a reason; acceptance/review fields are untouched. Activating a new Layer 3 revision marks the prior active revision superseded without deleting it. Restoring an accepted Layer 3 revision creates a new immutable active revision and evaluates its copied dependencies against current brief, pillar, and feature sources.

## Deterministic propagation rules

- Brief republish: follows exact old-publication edges into Layer 1, Layer 2, Layer 3, scope, coverage, and research targets; content and authority remain unchanged.
- Pillar title/description change, rename, or merge: follows the prior deterministic pillar content token to dependent Layer 2, Layer 3, scope, coverage, and research artifacts.
- Feature content change, rename, cut/replacement, or merge: follows the prior deterministic feature token to only that feature's Layer 3/coverage descendants.
- Pure keep/approve/needs-review changes: no content staleness.
- Repeated propagation: uniqueness of the source-change reason makes the history write idempotent.

Command results expose direct, transitive, already-stale, propagation count, reason, and completion fields. No route or model critic owns propagation.

## Affected execution paths

- Layer 0 form and Plan edits create draft revisions; `PublishBrief` owns atomic publication and propagation.
- Manual and generated Layer 1/2 creation records exact current lineage; their canonical edit commands propagate content changes.
- Layer 2 scope contracts, coverage matrices/memory, and research findings register current source versions when written.
- Layer 3 generation records exact available brief IDs and deterministic pillar/feature content tokens. Full/partial acceptance, edit, and restore preserve/copy dependencies and recalculate freshness.
- Project snapshots expose brief revision history plus Layer 1/2/3 freshness and stale reasons.
- Layer 3 export uses the shared freshness validator and blocks stale, missing, superseded, or mixed-lineage selections.
- Archive, clone, import, purge, and orphan cleanup include the new revision/dependency/history tables.

## Backfill classification

Migration v6 snapshots the current brief as an exact initial revision. Existing canonical descendants are conservatively linked to the current sources as inferred because their historical prompts did not retain immutable source revisions. Existing Layer 3 source strings are preserved, while new dependency edges are labeled inferred unless exact lineage is available. Unresolvable items remain unknown rather than receiving invented lineage.

The focused exact fixture has `exact=6`, `inferred=0`, `unknown=0`. The live PostgreSQL v5 fixture with one legacy pillar has `exact=0`, `inferred=1`, `unknown=0`. Fixtures deliberately assert these counts.

## Deferred lineage

- Layer 1 and Layer 2 use deterministic content tokens, not dedicated immutable revision tables.
- Negative memory remains durable human authority with its existing name/embedding fingerprint; it is not automatically invalidated.
- Overlap verdicts/clusters and assistant index documents continue safe lazy hash invalidation.
- Embeddings and cached summaries are rebuilt lazily on source-hash mismatch.
- Export files are validated at creation time; STRATA does not yet maintain a durable export-manifest table.
