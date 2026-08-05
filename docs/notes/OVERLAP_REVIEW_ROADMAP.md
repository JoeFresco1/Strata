# Modifications To Do

## Human-Loop Overlap Review

Status as of 2026-07-06:
- Implemented: dedicated Layer 1 and Layer 2 overlap review panels, per-verdict resolution actions, durable `overlap_verdict_resolutions`, active/stale resolution state in snapshots, unchanged-pair suppression for resolved verdicts, Layer 2 link/merge graph side effects, and backend regression coverage.
- Still to do: cluster-level bulk resolution, richer relation filters beyond unresolved/resolved/stale, prior-resolution prompt context, and dedicated frontend interaction tests.

Current overlap critic state:
- Layer 1 and Layer 2 overlap critic jobs can flag overlap.
- Verdicts are durable and tied to critic jobs.
- Stale verdicts are hidden after item edits.
- Layer 2 warnings are source-labeled so users can distinguish candidate overlap, graph critic, and overlap critic signals.
- Verdicts can now be resolved as accept merge, link, dismiss, keep separate, or needs follow-up.

Missing polish that would make the workflow feel product-grade:
- Add a cluster-level before/after flow so users can resolve a group of related items instead of chasing scattered warning icons.
- Add relation-specific filters for same capability, merge, fake novelty, broader/narrower, and link.
- Add prior user resolutions to critic prompt context so the model sees human judgment, not only shortlist suppression.
- Add dedicated frontend tests for the review panel actions and filters.

Desired outcome:
- Move from "AI warning badges" to a true human-in-the-loop review system where the AI flags overlap, the user resolves the specific verdict, and Strata remembers that judgment.

## Explainable Overlap Critique

The overlap critic should feel like a review judgment, not just a similarity score.

The UI should show what kind of decision pressure exists:
- Same capability: two items describe the same product capability and probably need one canonical version.
- Broader / narrower: one item contains the other, so the user may need to move the narrower concept under the broader one or clarify layer boundaries.
- Fake novelty: the wording sounds new, but the underlying capability is already covered elsewhere.
- Should merge: keeping both items would clutter the product map.
- Should link but remain separate: the items interact or depend on each other, but they should not be collapsed into one feature.

Example:
> Overlap critic: broader/narrower  
> "Assessment Builder" contains most of the scope of "Likert Scale Question Builder," but the latter is a specific response-type capability. Keep both only if Layer 2 is meant to capture question-type variants; otherwise move the narrower item under the broader one.

Desired outcome:
- Replace vague "similarity: 0.84" style feedback with actionable product-architecture reasoning.
- Make each verdict explain why the user should merge, link, keep separate, or rethink the item's level.
- Position the feature as an AI-assisted judgment system, not merely embedding-based duplicate detection.

## Implementation Plan

### Phase 1: Durable Resolution Model

Add persistent review state for overlap verdicts instead of treating verdicts as read-only warning badges.

Data model:
- Add `overlap_verdict_resolutions`.
- Store `project_id`, `verdict_id`, `layer`, `target_id`, `neighbor_id`, `action`, `note`, `resolved_by`, `target_hash`, `neighbor_hash`, `created_at`, and `updated_at`.
- Supported actions:
  - `accept_merge`
  - `link`
  - `dismiss`
  - `keep_separate`
  - `needs_followup`
- Store the item hashes at resolution time so the system can tell whether the decision still applies after later edits.

Behavior:
- A resolution applies only while both item hashes still match.
- If either item changes, keep the resolution for history but mark it inactive/stale in the API payload.
- Future overlap critic runs should suppress unchanged pairs that were dismissed or marked keep-separate.
- Future runs may still flag the pair again if either item changed enough to produce a new hash.

### Phase 2: API And Snapshot Shape

Expose overlap review as a first-class review workflow.

Backend endpoints:
- `GET /api/projects/{project_id}/overlap/{layer}/review`
- `POST /api/projects/{project_id}/overlap/{layer}/verdicts/{verdict_id}/resolve`
- `POST /api/projects/{project_id}/overlap/{layer}/clusters/{cluster_id}/resolve`

Snapshot additions:
- Include `resolved`, `active_resolution`, and `resolution_state` on each verdict.
- Include cluster rollups:
  - unresolved count
  - accepted merge count
  - linked count
  - dismissed count
  - stale resolution count

Rules:
- Latest completed overlap job remains the display source.
- Resolutions from older jobs can apply to new jobs only when the same item pair and item hashes match.
- Dismissed and keep-separate verdicts should remain visible in a resolved filter, but hidden from the default unresolved queue.

### Phase 3: Review Queue UI

Add a focused overlap review panel instead of relying only on table warning icons.

Placement:
- Add an `Overlap Review` panel or drawer reachable from Layer 1 and Layer 2.
- Keep warning icons in the main tables as entry points.
- Do not create a separate app-level surface; this belongs inside the layer workflow.

Default queue:
- Show unresolved latest verdicts first.
- Group by cluster when available.
- Show pairwise verdicts when no cluster exists.
- Let the user filter by:
  - unresolved
  - resolved
  - stale
  - same capability / merge
  - broader / narrower
  - fake novelty
  - link

Verdict card content:
- Target item title and description.
- Neighbor item title and description.
- Relation label.
- Confidence.
- Critic source.
- Rationale.
- Staleness state.
- Resolution history when present.

Actions:
- `Accept merge`
- `Link`
- `Dismiss`
- `Keep separate`
- `Needs follow-up`

Layer-specific action effects:
- Layer 1 `Accept merge`: record the resolution and guide the user to edit/retain the canonical pillar, because there is not yet a dedicated Layer 1 merge route.
- Layer 2 `Accept merge`: record the resolution and call the existing Layer 2 merge action when a target is selected.
- Layer 2 `Link`: record the resolution and create a `related_to` or `overlaps_with` relationship.
- `Dismiss` and `Keep separate`: record memory only; do not change the product graph.

### Phase 4: Explainability Polish

Make the verdict language read like product-architecture judgment.

UI copy:
- Replace raw relation IDs with plain labels:
  - `same_capability` -> Same capability
  - `broader` -> Target is broader
  - `narrower` -> Target is narrower
  - `fake_novelty` -> Fake novelty
  - `merge` -> Merge recommended
  - `link` -> Link, do not merge
  - `distinct` -> Distinct
  - `needs_review` -> Needs review

Rationale format:
- Require the critic to explain the decision pressure:
  - why the two items overlap
  - what would happen if both remain
  - what human action is recommended
- Avoid showing similarity score as the primary explanation.
- Similarity can appear as supporting metadata only.

Cluster explanation:
- Cluster cards should summarize the shared capability area.
- Show the likely canonical item if the critic can identify one.
- Show which items are duplicates, narrower variants, or related-but-separate.

### Phase 5: Learning From Human Decisions

Use resolved verdicts as project judgment for later critic runs.

Shortlist stage:
- Before LLM adjudication, check whether the item pair has an active `dismiss` or `keep_separate` resolution.
- Skip adjudication for unchanged dismissed/keep-separate pairs.
- Keep `accept_merge` and `link` decisions available as context so future runs do not rediscover them as unresolved warnings.

Prompt context:
- Add a compact `prior_resolutions` block to overlap critic prompts.
- Include only relevant prior decisions for the target and shortlisted neighbors.
- Tell the critic not to re-flag unchanged pairs already resolved by the user.

Audit trail:
- Preserve all resolutions.
- Never silently delete old verdicts.
- Make stale decisions inspectable but not active.

### Phase 6: Tests And Acceptance Criteria

Backend tests:
- Creating a verdict resolution persists the action and item hashes.
- Latest verdict payload includes active resolution state.
- Editing either item makes a prior resolution stale.
- Unchanged dismissed/keep-separate pairs are skipped in the next overlap run.
- Layer 2 `link` resolution creates the expected graph relationship.
- Layer 2 `accept_merge` resolution records the decision and invokes existing merge behavior.
- Layer 1 `accept_merge` records the decision without pretending a backend merge route exists.

Frontend tests/build checks:
- Overlap Review panel renders unresolved verdicts.
- Resolution actions are disabled for stale verdicts unless the user reruns the critic.
- Source labels remain visible.
- Filters separate unresolved, resolved, and stale verdicts.
- `npm run build` passes.

Acceptance criteria:
- A user can start from a warning icon, inspect the exact overlap reason, choose a resolution, and see that verdict leave the unresolved queue.
- A dismissed or keep-separate pair does not come back unchanged in the next critic run.
- A changed item can be reviewed again without losing the old decision history.
- Layer 2 merge/link decisions update the graph through existing review mechanics.
- The workflow reads as human-in-the-loop review, not passive AI annotations.
