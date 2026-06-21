LAYER2_LENSES: list[tuple[str, str]] = [
    ("core_workflows", "Find end-to-end capabilities users directly rely on inside this pillar."),
    ("user_actions", "Find concrete actions a user can take, without dropping to individual user-story wording."),
    ("background_automation", "Find system-driven automation, monitoring, cleanup, or scheduled capabilities."),
    ("edge_cases", "Find exception-handling capabilities for unusual, failed, or ambiguous situations."),
    ("admin_controls", "Find configuration, governance, permissioning, and operational control capabilities."),
    ("compliance", "Find auditability, privacy, risk, consent, policy, and regulatory-support capabilities."),
    ("data_requirements", "Find user-visible data capture, classification, enrichment, or validation capabilities."),
    ("integrations", "Find concrete third-party or internal interoperability capabilities."),
    ("reporting", "Find analytics, summaries, exports, and decision-support capabilities."),
    ("notifications", "Find alerts, reminders, nudges, escalation, or messaging capabilities."),
]

LAYER2_EXHAUSTION_FAMILIES: list[tuple[str, str]] = [
    ("core_capabilities", "Primary functions the module must perform."),
    ("variants_and_types", "Supported variants, modes, formats, or type inventories inside the module."),
    ("logic_and_rules", "Branching, rule, scoring, validation, and conditional behavior."),
    ("workflow_states", "Draft, review, publish, versioning, approval, and lifecycle states."),
    ("embedded_data", "Piped variables, contextual data, metadata, and reusable content inserted into the module."),
    ("templates_and_reuse", "Templates, cloning, reusable blocks, defaults, and pattern libraries."),
    ("admin_controls", "Configuration, governance, permissions, and operational controls specific to this module."),
    ("edge_cases", "Fallbacks, exceptions, error states, and uncommon but necessary module behavior."),
    ("integrations", "Inbound or outbound connections required inside this module boundary."),
    ("reporting_hooks", "Module-specific summaries, exports, audit traces, and handoffs to reporting."),
    ("accessibility_localization", "Accessibility, translation, formatting, and locale-specific support."),
]

LAYER2_SURVEY_BUILDER_FAMILIES: list[tuple[str, str]] = [
    ("question_types", "Question formats, answer inputs, matrix/ranking/open-ended variants, and media question support."),
    ("branching_logic", "Skip logic, display logic, branching rules, termination rules, and randomization."),
    ("workflow_states", "Drafting, review, approval, publishing, versioning, cloning, and rollback behavior."),
    ("embedded_data", "Piped text, respondent attributes, hidden fields, metadata, and carry-forward answer data."),
    ("scoring", "Scored questions, weighted answers, categories, thresholds, and result calculations."),
    ("templates_and_reuse", "Reusable question blocks, survey templates, themes, defaults, and question banks."),
    ("validation", "Required answers, ranges, formats, quotas, duplicate prevention, and response constraints."),
    ("distribution_setup", "Builder-owned launch configuration, availability windows, anonymous/authenticated mode, and embed setup."),
    ("accessibility_localization", "Accessible question rendering, translations, locale formats, and language variants."),
    ("collaboration_controls", "Comments, reviewer handoff, ownership, locks, and change approvals inside the builder."),
]

LAYER2_FEATURE_SCHEMA = """{
  "features": [
    {
      "canonical_name": "...",
      "description": "...",
      "feature_type": "workflow | automation | admin_control | compliance | data_requirement | integration | reporting | notification | capability",
      "coverage_family": "...",
      "scope_classification": "in_scope | adjacent_owned_elsewhere | new_layer1_pillar | too_low_level | implementation_detail",
      "pillar_fit_rationale": "...",
      "aliases": ["..."],
      "related_pillar_ids": ["..."],
      "depends_on": ["..."],
      "used_by": ["..."],
      "specificity_score": 0,
      "pillar_fit_score": 0,
      "distinctiveness_score": 0,
      "implementation_leakage_score": 0,
      "strategic_value_score": 0,
      "needs_human_review": true
    }
  ]
}"""

LAYER2_COVERAGE_SCHEMA = """{
  "coverage_summary": "...",
  "family_assessments": [
    {
      "family": "...",
      "status": "covered | partial | missing | excluded",
      "evidence_feature_ids": ["..."],
      "missing_examples": ["..."],
      "next_lens": "...",
      "rationale": "..."
    }
  ],
  "drifted_feature_ids": ["..."],
  "adjacent_module_suggestions": ["..."],
  "saturation_signal": "low | medium | high",
  "novelty_score": 0,
  "continue_recommendation": true,
  "recommended_next_lenses": ["..."],
  "reasoning": "..."
}"""

LAYER2_SCOPE_DISCOVERY_SCHEMA = """{
  "coverage_families": [
    {
      "name": "...",
      "description": "...",
      "exhaustion_goal": "...",
      "example_features": ["..."],
      "anti_examples": ["..."]
    }
  ],
  "reasoning": "..."
}"""

LAYER2_INTEGRITY_SCHEMA = """{
  "assessments": [
    {
      "candidate_id": "...",
      "granularity_class": "feature | feature_variant | workflow | rule | configuration | shared_concern | too_broad | too_low_level",
      "is_out_of_bounds": false,
      "ambiguity_score": 0.0,
      "reason": "..."
    }
  ]
}"""

LAYER2_GRAPH_CRITIC_SCHEMA = """{
  "duplicate_merges": [
    {"source_feature_id": "...", "target_feature_id": "...", "confidence": 0.0, "reason": "..."}
  ],
  "cross_pillar_dependencies": [
    {"source_feature_id": "...", "target_feature_id": "...", "relationship_type": "depends_on", "confidence": 0.0, "reason": "..."}
  ],
  "detected_shared_concerns": [
    {"name": "...", "concern_type": "ingestion", "connected_feature_ids": ["..."], "planning_implication": "...", "confidence": 0.0}
  ]
}"""
