# Critic Human-Authority Validation — 2026-07-20

## Invariant

A generated reviewer may challenge a durable human decision, but it cannot silently reverse, downgrade, merge, rename, supersede, or overwrite it.

## Mutation inventory

| Execution path | Model output | Artifact | Previous durable effect | Eligible state | Existing human action possible | Actor/origin before | Routing after this change |
|---|---|---|---|---|---|---|---|
| `layer1_engine._persist_layer1_round` | pillar assessment | new Layer 1 candidate | filter/quarantine, generated title, candidate insert | not yet persisted | no | model metadata only | automatic candidate routing |
| `generation._run_critic` | coverage critic | Layer 1 generation loop | coverage memory and stop/lens advice | all generated context | yes, only as prompt context | generation telemetry | advisory memory only |
| `layer1_overlap._apply_overlap_index_to_node` | deterministic similarity, not an LLM verdict | Layer 1 pillar | overlap-only JSON metadata refresh | active pillars | yes | none | deterministic metadata projection; no title/status/content replacement |
| `layer2_pipeline._persist_layer2_round` | integrity assessment | new Layer 2 candidate | initial status/category/metadata | never-reviewed candidate | no | model generation provenance | automatic candidate routing |
| `layer2_critics._apply_layer2_graph_directives` | duplicate/dependency/shared-concern directives | Layer 2 feature/graph | relationship insert, `needs_review`, system merge action | previously any feature | yes | system action was ambiguous | centralized policy; protected artifacts get findings only |
| `layer2_coverage._apply_layer2_drift_flags` | drift IDs | Layer 2 feature | `needs_review` plus metadata | previously any feature | yes | no action actor/origin | centralized policy; protected artifacts get findings only |
| `layer2_coverage._update_layer2_coverage_matrix_from_assessment` | coverage assessment | advisory coverage matrix | matrix/memory upsert | all | yes | model pass provenance | remains advisory; no canonical decision mutation |
| `overlap_critic.OverlapCriticRunner` | verdicts and clusters | overlap review records | inert verdict/cluster inserts | active items | yes | critic source/job retained | finding-only architecture retained; resolved pairs suppressed |
| `api_overlap._apply_overlap_resolution_side_effects` | none; explicit request | Layer 2 graph/status | accepted merge/link side effects | current non-stale verdict | yes, this is the human action | resolver/action retained | explicit command only |
| `research._run_layer1` | research assessment | Layer 1 pillar | research-profile JSON replacement | previously any pillar | yes | research job only | centralized policy; protected pillar gets finding only |
| `layer2_research._persist_layer2_assessments` | competitor assessment | evidence | append evidence rows | all | yes | research job/source retained | evidence-only behavior retained |
| assistant specialists and synthesis | reports/action proposals | any supported artifact | inert proposal insert | all | yes | conversation/run retained | proposal-only until confirmation |
| `api_support._execute_assistant_action` | user-confirmed proposal | node/feature/job | canonical service mutation | stale-checked proposal | yes | proposal status retained | records human authority with `assistant_confirmed` origin |
| retries/regeneration | same pass output | path-dependent | repeated prior effects | path-dependent | yes | job/retry metadata | same centralized policy and finding dedupe apply on every retry |
| Layer 3 generation/review routes | expansion candidate or explicit command | revisioned expansion | immutable candidate or atomic command | candidate/active revisions | yes | revision actor/origin/actions retained | accepted/restored revisions remain command-only; generated review is finding-only |

## Central policy

`CriticAuthorityPolicy` returns one typed disposition:

- `automatic_routing`: a generated, never-reviewed candidate may keep existing deterministic routing.
- `finding_only`: durable human authority exists; preserve the artifact and persist a challenge.
- `invalid`: bad artifact/reference/freshness transition, including model-opinion staleness.
- `requires_human_command`: reviewed state lacks enough authority provenance for automatic mutation.

The decision considers artifact type, durable action history, Layer 1 legacy decision state, Layer 2 review history, Layer 3 revision actions and field ownership, current actor/origin, review state, proposed action, source freshness, active revision, and whether the artifact is a new unreviewed candidate.

Human-authoritative actions include keep, cut, prioritize, approve, reject, rename, merge, edit, manual add, ownership/relationship decisions, accepted or partially applied Layer 3 candidates, restore, Layer 3 human edits/review decisions, overlap resolutions, and confirmed assistant actions. Legacy graph-critic merge recommendations are explicitly excluded from human authority.

## Finding persistence and migration

Migration v4 adds:

- `artifact_authority_actions`, an append-only actor/origin/action record;
- `critic_findings`, with logical artifact/revision identity, critic/policy/category/severity, explanation/evidence/recommendation, source fingerprint, model/job references, status, timestamps, and resolution metadata;
- unique dedupe on project + artifact + revision + critic + policy version + category + source fingerprint;
- project foreign keys, status/artifact checks, lifecycle indexes, and cleanup triggers for Layer 1, Layer 2, and Layer 3 artifact deletion.

Finding resolution updates the finding and writes the distinct human authority action in one transaction. It does not mutate the artifact; the existing explicit artifact command remains the only authoritative mutation route.

Review and freshness remain independent. A deterministic dependency change may set Layer 3 freshness to `stale` without changing an `approved` review state. Model opinion cannot set freshness.

## Verification

- Focused policy suite: 18 passed.
- Complete backend suite: 146 passed, plus 8 Layer 3 subtests.
- Live PostgreSQL 18 matrix: 2 passed, plus 5 subtests.
- PostgreSQL matrix covered v3→v4 migration, ownership validation, foreign keys, eight-way identical-result dedupe, rollback injection, transactional resolution, archive, clone, export/import, purge, artifact cleanup triggers, and disposable-database cleanup.
- Python compile check: passed.
- Frontend cache suite: 9 passed.
- Frontend production build: passed (existing Vite chunk-size warning only).

## Remaining direct generated-state effects

Only bounded effects remain:

- initial routing/filtering of never-reviewed Layer 1 and Layer 2 generated candidates;
- advisory coverage/scope memory and coverage matrices;
- deterministic overlap metadata projections;
- inert overlap verdicts/clusters and research evidence;
- Layer 1 research-profile updates on never-reviewed generated pillars;
- immutable Layer 3 candidate creation.

No known generated-review path directly mutates a human-protected canonical artifact. The finding data is included in project snapshots and API routes; this ticket does not add a new dedicated frontend finding-review panel.
