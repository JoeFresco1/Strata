from __future__ import annotations

from typing import Any


def add_layer1_territory_exploration(db: Any) -> None:
    """Create the canonical lossless Layer 1 exploration and synthesis stores."""
    json_type = "JSONB" if db.is_postgres else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if db.is_postgres else "TEXT"
    boolean_type = "BOOLEAN" if db.is_postgres else "INTEGER"
    _create_run_and_lens_tables(db, json_type, timestamp_type, boolean_type)
    _create_policy_tables(db, json_type, timestamp_type, boolean_type)
    _create_candidate_tables(db, json_type, timestamp_type, boolean_type)
    _create_coverage_and_synthesis_tables(db, json_type, timestamp_type, boolean_type)
    _create_indexes(db)
    _protect_immutable_records(db)


def _create_run_and_lens_tables(
    db: Any,
    json_type: str,
    timestamp_type: str,
    boolean_type: str,
) -> None:
    """Create exact-lineage runs, ordered lens work, and frozen attempt checkpoints."""
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_territory_runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_brief_revision_id TEXT NOT NULL,
            source_discovery_revision_id TEXT NOT NULL
                REFERENCES product_discovery_revisions(id) ON DELETE RESTRICT,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            config {json_type} NOT NULL,
            budget {json_type} NOT NULL,
            metrics {json_type} NOT NULL,
            incomplete_reason TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            updated_at {timestamp_type} NOT NULL,
            completed_at {timestamp_type}
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_lens_work_items (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_discovery_revision_id TEXT NOT NULL
                REFERENCES product_discovery_revisions(id) ON DELETE RESTRICT,
            source_lens_id TEXT NOT NULL,
            source_discovery_item_ids {json_type} NOT NULL,
            title TEXT NOT NULL,
            instruction TEXT NOT NULL,
            required {boolean_type} NOT NULL,
            discovery_order INTEGER NOT NULL,
            risk_priority INTEGER NOT NULL,
            relevance_score DOUBLE PRECISION NOT NULL,
            missing_coverage_priority INTEGER NOT NULL,
            human_priority INTEGER NOT NULL,
            human_order_position INTEGER,
            state TEXT NOT NULL,
            attempt_count INTEGER NOT NULL,
            max_attempts INTEGER NOT NULL,
            created_at {timestamp_type} NOT NULL,
            updated_at {timestamp_type} NOT NULL,
            UNIQUE(run_id, source_lens_id)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_lens_attempts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            lens_execution_id TEXT NOT NULL REFERENCES layer1_lens_work_items(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL,
            attempt_kind TEXT NOT NULL,
            status TEXT NOT NULL,
            settings {json_type} NOT NULL,
            source_projection {json_type} NOT NULL,
            closed_territory_revision_ids {json_type} NOT NULL,
            anti_generic_pattern_revision_ids {json_type} NOT NULL,
            prompt_key TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            prompt_projection_hash TEXT NOT NULL,
            raw_response TEXT NOT NULL,
            parsed_candidate_count INTEGER NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT NOT NULL,
            runtime_provenance {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL,
            started_at {timestamp_type},
            completed_at {timestamp_type},
            UNIQUE(lens_execution_id, attempt_number, attempt_kind)
        )
        """
    )


def _create_policy_tables(
    db: Any,
    json_type: str,
    timestamp_type: str,
    boolean_type: str,
) -> None:
    """Create append-only exclusions and anti-generic policy revisions."""
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_closed_territory_revisions (
            id TEXT PRIMARY KEY,
            logical_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            run_id TEXT REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            semantic_examples {json_type} NOT NULL,
            source_family_ids {json_type} NOT NULL,
            source TEXT NOT NULL,
            scope TEXT NOT NULL,
            active {boolean_type} NOT NULL,
            human_state TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor TEXT NOT NULL,
            command_id TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(logical_id, revision_number)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_anti_generic_pattern_revisions (
            id TEXT PRIMARY KEY,
            logical_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            semantic_examples {json_type} NOT NULL,
            source_run_ids {json_type} NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            scope TEXT NOT NULL,
            active {boolean_type} NOT NULL,
            human_state TEXT NOT NULL,
            actor TEXT NOT NULL,
            command_id TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(logical_id, revision_number)
        )
        """
    )


def _create_candidate_tables(
    db: Any,
    json_type: str,
    timestamp_type: str,
    boolean_type: str,
) -> None:
    """Create immutable raw territory plus append-only projections and decisions."""
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_territory_candidates (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            expansion_run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            lens_execution_id TEXT NOT NULL REFERENCES layer1_lens_work_items(id) ON DELETE CASCADE,
            lens_attempt_id TEXT NOT NULL REFERENCES layer1_lens_attempts(id) ON DELETE CASCADE,
            source_discovery_revision_id TEXT NOT NULL
                REFERENCES product_discovery_revisions(id) ON DELETE RESTRICT,
            source_lens_id TEXT NOT NULL,
            source_discovery_item_ids {json_type} NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            concrete_product_behavior TEXT NOT NULL,
            user_or_operator_value TEXT NOT NULL,
            affected_actor_ids {json_type} NOT NULL,
            affected_lifecycle_stage_ids {json_type} NOT NULL,
            affected_domain_ids {json_type} NOT NULL,
            affected_enterprise_obligation_ids {json_type} NOT NULL,
            affected_coverage_risk_ids {json_type} NOT NULL,
            lens_specific_mechanism TEXT NOT NULL,
            non_generic_rationale TEXT NOT NULL,
            proposed_destination TEXT NOT NULL,
            standalone_pillar_potential DOUBLE PRECISION NOT NULL,
            novelty_claim TEXT NOT NULL,
            feasibility_note TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            weakly_attributable {boolean_type} NOT NULL,
            raw_ordinal INTEGER NOT NULL,
            raw_model_payload {json_type} NOT NULL,
            runtime_provenance {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(lens_attempt_id, raw_ordinal)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_normalized_territories (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL REFERENCES layer1_territory_candidates(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            normalization_attempt_id TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            normalized_description TEXT NOT NULL,
            semantic_family TEXT NOT NULL,
            cluster_id TEXT,
            canonical_terminology TEXT NOT NULL,
            duplicate_of_candidate_id TEXT REFERENCES layer1_territory_candidates(id) ON DELETE SET NULL,
            merge_recommendation TEXT NOT NULL,
            abstraction_level_recommendation TEXT NOT NULL,
            destination_recommendation TEXT NOT NULL,
            normalization_dropped {boolean_type} NOT NULL,
            drop_reason TEXT NOT NULL,
            repair_attempt INTEGER NOT NULL,
            human_review_eligible {boolean_type} NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(candidate_id, normalization_attempt_id)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_territory_assessments (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL REFERENCES layer1_territory_candidates(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            assessor TEXT NOT NULL,
            destination_recommendation TEXT NOT NULL,
            lens_adherence_score INTEGER NOT NULL,
            useful_novelty_score INTEGER NOT NULL,
            generic_repetition_score INTEGER NOT NULL,
            quality_score INTEGER NOT NULL,
            attribution_score INTEGER NOT NULL,
            closed_territory_violation_ids {json_type} NOT NULL,
            anti_generic_pattern_ids {json_type} NOT NULL,
            rationale TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_territory_dispositions (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL REFERENCES layer1_territory_candidates(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            sequence_number INTEGER NOT NULL,
            destination TEXT NOT NULL,
            source TEXT NOT NULL,
            reason TEXT NOT NULL,
            supersedes_disposition_id TEXT REFERENCES layer1_territory_dispositions(id) ON DELETE SET NULL,
            target_artifact_id TEXT,
            actor TEXT NOT NULL,
            command_id TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(candidate_id, sequence_number)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_territory_clusters (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            semantic_family TEXT NOT NULL,
            candidate_ids {json_type} NOT NULL,
            representative_candidate_id TEXT REFERENCES layer1_territory_candidates(id) ON DELETE SET NULL,
            destination_summary {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(run_id, semantic_family)
        )
        """
    )


def _create_coverage_and_synthesis_tables(
    db: Any,
    json_type: str,
    timestamp_type: str,
    boolean_type: str,
) -> None:
    """Create separate lens/global coverage, adversarial, and immutable synthesis artifacts."""
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_lens_coverage_assessments (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            lens_execution_id TEXT NOT NULL REFERENCES layer1_lens_work_items(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL,
            addressed_discovery_item_ids {json_type} NOT NULL,
            unresolved_discovery_item_ids {json_type} NOT NULL,
            high_severity_unresolved_item_ids {json_type} NOT NULL,
            lens_adherence_score INTEGER NOT NULL,
            useful_novelty_score INTEGER NOT NULL,
            generic_repetition_rate DOUBLE PRECISION NOT NULL,
            duplicate_rate DOUBLE PRECISION NOT NULL,
            weak_attribution_rate DOUBLE PRECISION NOT NULL,
            recommendation TEXT NOT NULL,
            rationale TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(lens_execution_id, attempt_number)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_adversarial_scenarios (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL UNIQUE REFERENCES layer1_territory_candidates(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            scenario TEXT NOT NULL,
            affected_actor_id TEXT NOT NULL,
            insufficient_territory_ids {json_type} NOT NULL,
            concrete_failure TEXT NOT NULL,
            missing_product_territory TEXT NOT NULL,
            distinctness_rationale TEXT NOT NULL,
            proposed_destination TEXT NOT NULL,
            severity TEXT NOT NULL,
            source_discovery_item_ids {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_coverage_states (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            discovery_coverage {json_type} NOT NULL,
            territory_diversity {json_type} NOT NULL,
            lens_adherence {json_type} NOT NULL,
            candidate_integrity {json_type} NOT NULL,
            architecture_breadth {json_type} NOT NULL,
            runtime_cost {json_type} NOT NULL,
            unresolved_high_severity_item_ids {json_type} NOT NULL,
            ready_for_synthesis {boolean_type} NOT NULL,
            incomplete_reasons {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(run_id, version)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_architecture_candidates (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            version INTEGER NOT NULL,
            title TEXT NOT NULL,
            rationale TEXT NOT NULL,
            pillars {json_type} NOT NULL,
            significant_non_pillar_territory_ids {json_type} NOT NULL,
            unresolved_risk_ids {json_type} NOT NULL,
            content_hash TEXT NOT NULL,
            runtime_provenance {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(run_id, kind, version),
            UNIQUE(run_id, content_hash)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_pillar_territory_mappings (
            id TEXT PRIMARY KEY,
            architecture_candidate_id TEXT NOT NULL
                REFERENCES layer1_architecture_candidates(id) ON DELETE CASCADE,
            pillar_id TEXT NOT NULL,
            territory_candidate_ids {json_type} NOT NULL,
            source_discovery_item_ids {json_type} NOT NULL,
            covered_actor_ids {json_type} NOT NULL,
            covered_domain_ids {json_type} NOT NULL,
            covered_enterprise_obligation_ids {json_type} NOT NULL,
            covered_risk_ids {json_type} NOT NULL,
            cross_cutting_concern_ids {json_type} NOT NULL,
            subordinate_feature_family_ids {json_type} NOT NULL,
            UNIQUE(architecture_candidate_id, pillar_id)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_synthesis_results (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            source_coverage_state_id TEXT NOT NULL REFERENCES layer1_coverage_states(id) ON DELETE RESTRICT,
            architecture_candidate_ids {json_type} NOT NULL,
            retained_non_pillar_territory_ids {json_type} NOT NULL,
            status TEXT NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT NOT NULL,
            runtime_provenance {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_global_architecture_assessments (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            architecture_candidate_ids {json_type} NOT NULL,
            product_domain_coverage_score INTEGER NOT NULL,
            actor_coverage_score INTEGER NOT NULL,
            lifecycle_coverage_score INTEGER NOT NULL,
            enterprise_obligation_coverage_score INTEGER NOT NULL,
            differentiation_score INTEGER NOT NULL,
            coherence_score INTEGER NOT NULL,
            overbroad_pillar_ids {json_type} NOT NULL,
            fragmented_pillar_ids {json_type} NOT NULL,
            hidden_territory_candidate_ids {json_type} NOT NULL,
            unresolved_high_severity_risk_ids {json_type} NOT NULL,
            needs_additional_exploration_lens {boolean_type} NOT NULL,
            recommended_lens TEXT NOT NULL,
            ready_for_human_review {boolean_type} NOT NULL,
            rationale TEXT NOT NULL,
            runtime_provenance {json_type} NOT NULL,
            created_at {timestamp_type} NOT NULL
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_architecture_selection_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            sequence_number INTEGER NOT NULL,
            architecture_candidate_id TEXT NOT NULL
                REFERENCES layer1_architecture_candidates(id) ON DELETE RESTRICT,
            state TEXT NOT NULL,
            actor TEXT NOT NULL,
            command_id TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE(run_id, sequence_number)
        )
        """
    )


def _create_indexes(db: Any) -> None:
    """Create project, run, lineage, and review lookup indexes."""
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_l1_territory_runs_project ON layer1_territory_runs(project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_l1_lens_work_run ON layer1_lens_work_items(run_id, state)",
        "CREATE INDEX IF NOT EXISTS idx_l1_lens_attempt_run ON layer1_lens_attempts(run_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_l1_closed_project ON layer1_closed_territory_revisions(project_id, logical_id, revision_number)",
        "CREATE INDEX IF NOT EXISTS idx_l1_generic_project ON layer1_anti_generic_pattern_revisions(project_id, logical_id, revision_number)",
        "CREATE INDEX IF NOT EXISTS idx_l1_candidate_run ON layer1_territory_candidates(expansion_run_id, lens_execution_id)",
        "CREATE INDEX IF NOT EXISTS idx_l1_disposition_candidate ON layer1_territory_dispositions(candidate_id, sequence_number)",
        "CREATE INDEX IF NOT EXISTS idx_l1_cluster_run ON layer1_territory_clusters(run_id, semantic_family)",
        "CREATE INDEX IF NOT EXISTS idx_l1_coverage_run ON layer1_coverage_states(run_id, version)",
        "CREATE INDEX IF NOT EXISTS idx_l1_architecture_run ON layer1_architecture_candidates(run_id, kind, version)",
        "CREATE INDEX IF NOT EXISTS idx_l1_global_architecture_run ON layer1_global_architecture_assessments(run_id, created_at)",
    ):
        db._execute(statement)


def _protect_immutable_records(db: Any) -> None:
    """Protect raw candidates and architecture contents from in-place mutation."""
    immutable_tables = (
        "layer1_territory_candidates",
        "layer1_architecture_candidates",
        "layer1_pillar_territory_mappings",
    )
    if db.is_postgres:
        db._execute(
            """
            CREATE OR REPLACE FUNCTION strata_protect_layer1_territory_immutable()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Layer 1 territory and architecture records are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in immutable_tables:
            trigger = f"protect_{table}_update"
            db._execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            db._execute(
                f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} FOR EACH ROW "
                "EXECUTE FUNCTION strata_protect_layer1_territory_immutable()"
            )
        return
    for table in immutable_tables:
        db._execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS protect_{table}_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, 'Layer 1 territory and architecture records are immutable');
            END
            """
        )
