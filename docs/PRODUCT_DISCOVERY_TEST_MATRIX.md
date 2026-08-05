# Product Discovery Acceptance Matrix

This matrix maps the goal's 50 required checks to focused or existing
regression evidence. The focused suite is `tests/test_product_discovery.py`;
the unchanged platform regression suite is `tests/test_core.py`.

| # | Required behavior | Evidence |
|---:|---|---|
| 1 | Requires published Layer 0 | `test_generation_requires_current_published_brief` |
| 2 | Exact brief revision lineage | `test_snapshot_exposes_discovery_and_exact_source_revision` |
| 3 | New brief marks discovery stale | `test_new_brief_publication_marks_discovery_stale_with_exact_reason` |
| 4 | Regeneration/revision is append-only | `test_human_fields_and_exclusions_survive_new_candidate_revisions` |
| 5 | Published discovery cannot be overwritten | `test_revision_lifecycle_is_versioned_and_published_content_is_immutable` |
| 6 | Model and human fields remain separate | `test_human_fields_and_exclusions_survive_new_candidate_revisions` |
| 7 | Human lenses survive later candidates | human-owned lens projection path plus replacement-revision test |
| 8 | Human exclusions remain authoritative | `test_projection_is_reproducible_and_honors_exclusions` |
| 9 | Baseline lenses cannot disappear | `test_normalization_assigns_stable_ids_and_all_baseline_lenses` |
| 10 | Super-administration is evaluated | same baseline test |
| 11 | Domains may overlap | same normalization test |
| 12 | Stable nested IDs | same normalization test |
| 13 | Durable review disposition and rationale | `test_practicality_review_flags_superficial_and_retains_unusual_ideas` |
| 14 | Superficial analogies are flagged, not deleted | same review test |
| 15 | Unusual defensible ideas reach human review | same review test |
| 16 | Raw model response retained | `test_human_fields_and_exclusions_survive_new_candidate_revisions` |
| 17 | Job/revision results are JSON-safe | `test_schema_names_and_job_results_are_json_safe` |
| 18 | Optimistic concurrency | `test_optimistic_concurrency_rejects_conflicting_human_edits` |
| 19 | Idempotent generation command | `test_generate_command_is_idempotent_and_never_starts_research` |
| 20 | Canonical snapshot exposure | `test_snapshot_exposes_discovery_and_exact_source_revision` |
| 21 | Existing Layer 0 publication | `tests/test_core.py` |
| 22 | Existing Layer 1/2/3 workflows | `tests/test_core.py` |
| 23 | No automatic Layer 1 job | generation-command job assertion plus `tests/test_core.py` |
| 24 | Completes with research disabled | no-research command/mode tests |
| 25 | Research requires explicit enablement | `test_competitor_modes_have_distinct_budgets_and_none_cannot_run` |
| 26 | Lightweight/deep budgets differ | same mode test |
| 27 | Research failure does not invalidate core discovery | `test_failed_or_cancelled_research_jobs_leave_core_discovery_valid` |
| 28 | Cancellation does not invalidate core discovery | same terminal-job independence test |
| 29 | Partial results persist | `test_partial_research_is_independent_and_compacts_only_approved_findings` |
| 30 | Pillars contain evidence/confidence | typed validation in the partial research test |
| 31 | Inference is not official architecture | typed `inference_strength` plus evidence-enforcement tests |
| 32 | Unsupported findings are rejected | `test_competitor_inference_requires_real_evidence_ids` |
| 33 | Independent approve/exclude/stale decisions | partial projection test and `test_competitor_finding_can_be_marked_stale_independently` |
| 34 | Research cannot alter published discovery | `test_research_cannot_silently_attach_or_change_published_discovery` |
| 35 | Exclusions survive research regeneration | checkpoint workflow carries prior `human_decisions`; replacement tests |
| 36 | Research freshness is independent | `test_competitor_finding_can_be_marked_stale_independently` |
| 37 | Competitive context omits raw corpora | partial projection test |
| 38 | Discovery context omits excluded items | discovery projection test |
| 39 | Projection reproducibility | both projection tests |
| 40 | Competitive context independent retrieval | API schema audit and competitive projection test |
| 41 | Source/date/mode/prompt/runtime provenance | typed partial research and runtime provenance tests |
| 42 | Exact model identifier/file | `test_runtime_provenance_resolves_alias_and_competitor_prompt_identity` |
| 43 | Alias resolves to authoritative provenance | same runtime test |
| 44 | One competitor may finish while another remains unresolved | partial research test |
| 45 | Missing evidence cannot create findings | evidence-ID enforcement test |
| 46 | Derived lenses require evidence/confidence | typed schema and service evidence filter |
| 47 | Table-stakes remains advisory | `CompetitiveTerritory.advisory_only` validation and compiler behavior |
| 48 | Research cannot force domains/pillars | independent artifacts and advisory-only compiler |
| 49 | Existing command/audit/platform tests | `tests/test_core.py` |
| 50 | Existing and focused suites pass | final verification commands below |

Verification commands:

```powershell
$env:STRATA_DB_BACKEND='sqlite'
$env:STRATA_DB_PATH=Join-Path $env:TEMP ('strata-core-' + [guid]::NewGuid().ToString() + '.db')
.\.venv\Scripts\python.exe -m pytest tests\test_core.py -q

$env:STRATA_DB_PATH=Join-Path $env:TEMP ('strata-discovery-' + [guid]::NewGuid().ToString() + '.db')
.\.venv\Scripts\python.exe -m pytest tests\test_product_discovery.py -q

Set-Location frontend
node --test tests/*.test.mjs
npm run build
```
