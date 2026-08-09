# Layer 1 territory exploration

Layer 1 now uses the breadth-first workflow as its canonical generated path,
while preserving manual pillar authoring and backward-compatible requests. It consumes the exact published Layer 0 and Product Discovery
revisions, runs each discovery lens independently, preserves every raw candidate,
and delays pillar synthesis until exploration is complete.

The workspace is available under
**Layer 1 → Territory exploration**.

## Workflow

1. Start an exploration run. The application freezes the published brief,
   discovery lineage, divergence policy, hard budget, and deterministic lens
   queue.
2. Run independent lens attempts. Each call receives only the source projection,
   one lens, directly related discovery IDs, approved exclusions, approved
   anti-generic patterns, and the territory schema.
3. Persist raw candidates immediately. Every candidate receives an explicit
   pending disposition before normalization and classification.
4. Create non-destructive normalized projections, assessments, current
   destinations, semantic clusters, and lens-local coverage.
5. Run an optional adversarial failure-scenario pass through the same ledger.
6. When application-owned global stopping rules are satisfied, generate at least
   two immutable, mapped architecture options.
7. Run the global architecture critic separately. Human selection is an
   append-only event and does not overwrite other options or existing pillars.
8. Apply the selected option through a separate, explicit human command. The
   application validates exact current pillar state tokens, preserves replaced
   pillars as cut history, and records retained non-pillar territory for Layers
   2 and 3.

Hard call, elapsed-time, and candidate budgets produce an `incomplete` or
`budget_exhausted` result. They never imply saturation.

## Candidate destination model

The current destination is exactly one of the typed values in
`TerritoryDestination`. Useful territory can remain a cross-cutting concern,
enterprise obligation, pillar extension, Layer 2 feature family, actor workspace,
operational/commercial/developer capability, workflow, decision mechanism, data
responsibility, governance mechanism, or strategic opportunity. It is not reduced
to “pillar or reject.”

Raw candidates and architecture contents are immutable. Normalization,
assessments, dispositions, policy revisions, and architecture selections retain
their history.

## API and commands

The canonical commands are defined in `strata/command_types.py` and execute
through the existing idempotency, audit, authority, and optimistic-concurrency
boundary. The HTTP surface is rooted at:

```text
/api/projects/{project_id}/layer1/exploration-runs
```

The run detail response includes lens work, frozen attempts, raw and normalized
candidates, full disposition history, clusters, lens/global coverage, policy
history, adversarial findings, architecture options, global critic results,
runtime provenance, and metrics.

Commands that enqueue territory, adversarial, or synthesis work schedule the
durable job immediately after the command transaction succeeds. Lens actions
round-trip their optimistic-concurrency state token through the HTTP API.

Architecture selection, application, and downstream Layer 2/3 generation require
the exact current brief, Product Discovery, and active architecture application.
Superseded applications remain auditable but cannot receive new descendants.
Local runtime preflight uses provider tokenizer routes when available and a
conservative bounded estimate for OpenAI-compatible providers such as LM Studio
or Ollama that do not expose llama.cpp tokenizer endpoints.

Project archive, clone, purge, and restore include the new canonical tables,
including architecture applications and their downstream lineage.

## Controlled evaluation

Run both arms with the same model:

```powershell
python -m scripts.layer1_territory_eval `
  --arm existing `
  --database .runtime/layer1-eval/existing.sqlite3 `
  --output .runtime/layer1-eval/existing.json `
  --profile-label local-control `
  --model-name gemma-4-12b-it-UD-Q6_K_XL `
  --model-path C:\models\gemma-4-12b-it-UD-Q6_K_XL.gguf `
  --max-output-tokens 10000 `
  --timeout-seconds 3600

python -m scripts.layer1_territory_eval `
  --arm divergent `
  --database .runtime/layer1-eval/divergent.sqlite3 `
  --output .runtime/layer1-eval/divergent.json `
  --profile-label local-control `
  --model-name gemma-4-12b-it-UD-Q6_K_XL `
  --model-path C:\models\gemma-4-12b-it-UD-Q6_K_XL.gguf
```

Repeat the divergent command with a stronger model when one is available. Every
result records the exact model-file size and SHA-256 when `--model-path` is
provided. It also records a fixture hash so results from different source
fixtures cannot be silently compared.

The controlled local experiment uses 15 candidates per lens because 18
full-attribution candidates exceeded the tested model's structured-output
envelope. A diagnostic 8,000-token run also truncated one 15-candidate lens, so
the final same-model control uses a 10,000-token ceiling. One call also exceeded
the initial 2,400-second timeout, so the final control uses 3,600 seconds. The
product default remains 18; these are experiment-specific sizing decisions, not
hidden production changes.

The fixed fixture evaluates:

- Actors, Authority, and Decision Rights;
- Enterprise Administration and Operations;
- Data, Integrations, and Evidence Quality.

Metrics cover semantic families, lens adherence, generic repetition, actor and
enterprise-obligation coverage, operational territory, candidate usefulness,
malformed output, and elapsed time. Candidate or pillar count alone is not a
success criterion.

## Required-test traceability

| Goal test | Focused evidence |
|---|---|
| 1–5 | `test_raw_candidate_is_immutable_and_missing_attribution_is_flagged`, `test_normalization_preserves_every_raw_candidate_and_marks_omissions` |
| 6–11 | `test_prompt_is_lens_local_and_includes_effective_exclusions`, `test_closed_territory_can_be_reopened_and_pattern_revisions_are_auditable`, `test_closed_territory_violation_is_rejected_without_candidate_deletion` |
| 12–16 | `test_candidate_integrity_metrics_are_reproducible`, `test_no_new_pillar_can_complete_lens_with_subordinate_territory`, `test_global_completion_cannot_skip_required_lenses_or_hide_budget_exhaustion` |
| 17–20 | `test_lens_order_uses_required_risk_relevance_missing_and_human_priority`, `test_temperature_changes_only_for_configured_unresolved_conditions`, `test_attempt_settings_remain_frozen_across_checkpoints`, `test_independent_retry_preserves_raw_but_does_not_duplicate_acceptance` |
| 21–25 | `test_adversarial_findings_share_ledger_and_synthesis_uses_mapped_territory`, `test_human_disposition_supersedes_model_without_deleting_history` |
| 26–30 | `test_architectures_coexist_and_selection_does_not_mutate_content`, `test_failed_global_critic_preserves_synthesis_and_earlier_checkpoints` |
| 31–33 | `test_candidate_integrity_metrics_are_reproducible`, `test_fixture_hash_is_identical_across_isolated_profile_runs`, `test_run_rejects_non_current_or_unpublished_lineage` |
| 34–35 | Existing Product Discovery and full regression suites plus the focused Layer 1 suites |
