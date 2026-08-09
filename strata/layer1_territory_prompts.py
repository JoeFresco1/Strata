from __future__ import annotations

import json
from typing import Any

from strata.layer1_territory_models import AntiGenericPattern, ClosedTerritory


TERRITORY_OUTPUT_SCHEMA = {
    "candidates": [
        {
            "candidate_id": "stable ID",
            "source_discovery_item_ids": ["exact provided IDs"],
            "title": "territory name",
            "description": "territory boundary",
            "concrete_product_behavior": "what the product does",
            "user_or_operator_value": "who benefits and how",
            "affected_actor_ids": [],
            "affected_lifecycle_stage_ids": [],
            "affected_domain_ids": [],
            "affected_enterprise_obligation_ids": [],
            "affected_coverage_risk_ids": [],
            "lens_specific_mechanism": "mechanism introduced by this lens",
            "non_generic_rationale": "why this is not generic lifecycle territory",
            "proposed_destination": "one supported destination",
            "standalone_pillar_potential": 0.5,
            "novelty_claim": "what is materially new",
            "feasibility_note": "key implementation constraint",
            "confidence": 0.5,
        }
    ]
}


def build_territory_divergence_prompt(
    *,
    brief_projection: dict[str, Any],
    discovery_revision_id: str,
    lens: dict[str, Any],
    relevant_discovery_items: list[dict[str, Any]],
    required_source_ids: dict[str, list[str]],
    closed_territories: list[ClosedTerritory],
    anti_generic_patterns: list[AntiGenericPattern],
    target_count: int,
    minimum_count: int,
) -> str:
    """Build a context-independent high-quantity territory prompt for one lens."""
    closed_text = _closed_territory_text(closed_territories)
    generic_text = _anti_generic_text(anti_generic_patterns)
    destinations = (
        "standalone_pillar_candidate, cross_cutting_product_concern, "
        "enterprise_platform_obligation, pillar_extension, layer_2_feature_family, "
        "actor_workspace, operational_capability, commercial_capability, "
        "developer_platform_capability, workflow_family, decision_mechanism, "
        "data_responsibility, governance_mechanism, strategic_opportunity, "
        "deferred_human_review, duplicate, out_of_scope, rejected_quality, "
        "rejected_generic_repetition, rejected_unsupported, rejected_bizarre"
    )
    return f"""
You are performing divergent product-territory exploration for exactly one discovery lens.
This is not pillar synthesis. Do not propose a compact framework or final architecture.

Generate {target_count} raw product-territory candidates. Returning fewer than
{minimum_count} because the smaller set seems better is not preferred.

Breadth rules:
- do not self-edit toward elegance;
- do not merge related candidates;
- overlap and uneven quality are allowed because classification happens later;
- include operational, administrative, commercial, technical, and actor-specific territory;
- include plausible niche and unusual but concrete territory;
- speculative territory is allowed when clearly labeled;
- every item must describe concrete product behavior;
- keep every prose field to one concise sentence and use IDs only in ID arrays;
- use exactly one proposed destination from: {destinations}.

Published Layer 0 projection:
{json.dumps(brief_projection, ensure_ascii=False, sort_keys=True)}

Published Product Discovery revision: {discovery_revision_id}
Assigned lens:
{json.dumps(lens, ensure_ascii=False, sort_keys=True)}

Only discovery items relevant to this lens:
{json.dumps(relevant_discovery_items, ensure_ascii=False, sort_keys=True)}

Required source IDs by type:
{json.dumps(required_source_ids, ensure_ascii=False, sort_keys=True)}

{closed_text}

{generic_text}

Do not use or infer conversational history from any prior lens call. Generate only
territory introduced or materially changed by the assigned lens. If an idea interacts
with closed territory, it is valid only when it introduces a materially new
lens-specific mechanism.

Return JSON matching this shape:
{json.dumps(TERRITORY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}
""".strip()


def build_lens_coverage_prompt(
    *,
    lens: dict[str, Any],
    required_discovery_item_ids: list[str],
    candidate_projection: list[dict[str, Any]],
) -> str:
    """Build a lens-local critic prompt that cannot terminate global exploration."""
    return f"""
Evaluate only the assigned discovery lens. Do not judge the final pillar architecture
and do not claim the whole design space is exhausted.

Lens:
{json.dumps(lens, ensure_ascii=False, sort_keys=True)}

Required discovery item IDs:
{json.dumps(required_discovery_item_ids)}

Preserved candidate projections:
{json.dumps(candidate_projection, ensure_ascii=False, sort_keys=True)}

Determine lens adherence, useful novelty, generic repetition, duplication, weak
attribution, addressed IDs, unresolved IDs, and high-severity unresolved IDs.
Recommend one bounded next step.

Return JSON:
{{
  "addressed_discovery_item_ids": [],
  "unresolved_discovery_item_ids": [],
  "high_severity_unresolved_item_ids": [],
  "lens_adherence_score": 0,
  "useful_novelty_score": 0,
  "generic_repetition_rate": 0.0,
  "duplicate_rate": 0.0,
  "weak_attribution_rate": 0.0,
  "recommendation": "continue_same_configuration | retry_with_stronger_exclusions | retry_with_higher_temperature | retry_with_alternate_prompt | mark_saturated | covered_with_subordinate_territory | requires_human_review | blocked_by_model | budget_exhausted",
  "rationale": ""
}}
""".strip()


def build_adversarial_territory_prompt(
    *,
    role: str,
    brief_projection: dict[str, Any],
    discovery_projection: dict[str, Any],
    current_territory_projection: list[dict[str, Any]],
    territory_inventory: dict[str, list[str]] | None = None,
    territory_population_summary: dict[str, Any] | None = None,
    semantic_clusters: list[dict[str, Any]] | None = None,
) -> str:
    """Ask for concrete failure scenarios rather than another pillar brainstorm."""
    return f"""
Act as a {role}. Assume the current product-territory map is incomplete and will fail
in production. Do not propose pillars and do not rewrite existing territory.

Identify concrete customer, operator, administrative, commercial, integration,
privacy, migration, or governance scenarios the current map cannot support.
Return exactly five highest-value scenarios. Keep every prose field to one concise
sentence so the JSON object closes within the reserved response budget.

Published Layer 0:
{json.dumps(brief_projection, ensure_ascii=False, sort_keys=True)}

Bounded Product Discovery:
{json.dumps(discovery_projection, ensure_ascii=False, sort_keys=True)}

Current accepted territory projection:
{json.dumps(current_territory_projection, ensure_ascii=False, sort_keys=True)}

Complete accepted-territory inventory grouped by destination:
{json.dumps(territory_inventory if territory_inventory is not None else current_territory_projection, ensure_ascii=False, sort_keys=True)}

Accepted-territory population summary:
{json.dumps(territory_population_summary or {}, ensure_ascii=False, sort_keys=True)}

Semantic-family summaries:
{json.dumps(semantic_clusters or [], ensure_ascii=False, sort_keys=True)}

Return JSON:
{{
  "scenarios": [{{
    "scenario": "",
    "affected_actor_id": "",
    "insufficient_territory_ids": [],
    "concrete_failure": "",
    "missing_product_territory": "",
    "distinctness_rationale": "",
    "proposed_destination": "deferred_human_review",
    "severity": "low | medium | high | critical",
    "source_discovery_item_ids": []
  }}]
}}
""".strip()


def build_architecture_synthesis_prompt(
    *,
    brief_projection: dict[str, Any],
    discovery_projection: dict[str, Any],
    territory_projection: list[dict[str, Any]],
    territory_inventory: dict[str, list[str]] | None = None,
    territory_population_summary: dict[str, Any] | None = None,
    semantic_clusters: list[dict[str, Any]],
    unresolved_high_severity_risk_ids: list[str],
    requested_views: list[str],
) -> str:
    """Build a bounded synthesis prompt from accepted territory, never raw transcripts."""
    return f"""
Synthesize Layer 1 architecture options only from the accepted and routed territory
projection below. Do not use raw transcripts, rejected nonsense, or competitor corpora.
Do not force a pillar count. Significant useful non-pillar territory must remain listed.

Requested views:
{json.dumps(requested_views)}

Published Layer 0:
{json.dumps(brief_projection, ensure_ascii=False, sort_keys=True)}

Published Product Discovery:
{json.dumps(discovery_projection, ensure_ascii=False, sort_keys=True)}

Accepted and routed territory:
{json.dumps(territory_projection, ensure_ascii=False, sort_keys=True)}

Complete accepted-territory inventory grouped by destination:
{json.dumps(territory_inventory if territory_inventory is not None else territory_projection, ensure_ascii=False, sort_keys=True)}

Accepted-territory population summary:
{json.dumps(territory_population_summary or {}, ensure_ascii=False, sort_keys=True)}

Semantic clusters:
{json.dumps(semantic_clusters, ensure_ascii=False, sort_keys=True)}

Unresolved high-severity risk IDs:
{json.dumps(unresolved_high_severity_risk_ids)}

Every pillar must map to one or more exact territory candidate IDs from either the
detailed projection or compact inventory. Keep rationales and descriptions concise;
use no more than eight representative territory IDs in each pillar mapping. Set
`significant_non_pillar_territory_ids` to an empty list: the application—not the
model—will deterministically populate it with every accepted unmapped candidate.
Return JSON:
{{
  "architectures": [{{
    "kind": "coherent_core | expansive_differentiation | enterprise_completeness",
    "title": "",
    "rationale": "",
    "pillars": [{{"id": "", "title": "", "description": ""}}],
    "mappings": [{{
      "pillar_id": "",
      "territory_candidate_ids": [],
      "source_discovery_item_ids": [],
      "covered_actor_ids": [],
      "covered_domain_ids": [],
      "covered_enterprise_obligation_ids": [],
      "covered_risk_ids": [],
      "cross_cutting_concern_ids": [],
      "subordinate_feature_family_ids": []
    }}],
    "significant_non_pillar_territory_ids": [],
    "unresolved_risk_ids": []
  }}]
}}
""".strip()


def build_global_architecture_critic_prompt(
    *,
    architectures: list[dict[str, Any]],
    coverage_state: dict[str, Any],
) -> str:
    """Evaluate architecture-level coverage without revisiting lens saturation."""
    return f"""
Evaluate the candidate Layer 1 architectures as a whole. This is an architecture
critic, not a lens-coverage evaluator. Do not claim exploration is exhausted and do
not change any candidate.

Candidate architectures:
{json.dumps(architectures, ensure_ascii=False, sort_keys=True)}

Application-owned global coverage state:
{json.dumps(coverage_state, ensure_ascii=False, sort_keys=True)}

Evaluate product domains, actors, lifecycle, enterprise obligations, differentiation,
coherence, overbreadth, fragmentation, hidden retained territory, and unresolved
high-severity risks. If another lens is warranted, identify it explicitly.

Return JSON:
{{
  "product_domain_coverage_score": 0,
  "actor_coverage_score": 0,
  "lifecycle_coverage_score": 0,
  "enterprise_obligation_coverage_score": 0,
  "differentiation_score": 0,
  "coherence_score": 0,
  "overbroad_pillar_ids": [],
  "fragmented_pillar_ids": [],
  "hidden_territory_candidate_ids": [],
  "unresolved_high_severity_risk_ids": [],
  "needs_additional_exploration_lens": false,
  "recommended_lens": "",
  "ready_for_human_review": false,
  "rationale": ""
}}
""".strip()


def _closed_territory_text(closed_territories: list[ClosedTerritory]) -> str:
    """Render approved semantic exclusions with IDs for violation attribution."""
    if not closed_territories:
        return "Closed territory set: none."
    items = [
        {
            "revision_id": item.id,
            "logical_id": item.logical_id,
            "title": item.title,
            "description": item.description,
            "semantic_examples": item.semantic_examples,
        }
        for item in closed_territories
    ]
    return (
        "The following product territories are already represented and closed for this "
        "pass. Do not propose narrower, broader, renamed, adjacent, or repackaged "
        f"versions:\n{json.dumps(items, ensure_ascii=False, sort_keys=True)}"
    )


def _anti_generic_text(patterns: list[AntiGenericPattern]) -> str:
    """Render active human-approved generic-pattern controls."""
    if not patterns:
        return "Active anti-generic patterns: none."
    items = [
        {
            "revision_id": item.id,
            "title": item.title,
            "description": item.description,
            "semantic_examples": item.semantic_examples,
        }
        for item in patterns
    ]
    return (
        "Do not return candidates that merely instantiate these generic patterns. A "
        "materially new lens-specific mechanism remains allowed:\n"
        f"{json.dumps(items, ensure_ascii=False, sort_keys=True)}"
    )
