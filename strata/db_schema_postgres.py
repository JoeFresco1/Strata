from __future__ import annotations


class PostgresSchemaMixin:
    """Create and migrate the PostgreSQL schema."""

    def _initialize_postgres(self) -> None:
        """Create the PostgreSQL schema and enable pgvector for future retrieval work."""
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        idea TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_briefs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
                        product_idea TEXT NOT NULL,
                        known_competitors JSONB NOT NULL,
                        constraints TEXT NOT NULL,
                        target_users TEXT NOT NULL DEFAULT '',
                        goals JSONB NOT NULL DEFAULT '[]'::jsonb,
                        preferred_directions JSONB NOT NULL DEFAULT '[]'::jsonb,
                        rejected_directions JSONB NOT NULL DEFAULT '[]'::jsonb,
                        notes TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'draft',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_model_settings (
                        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                        llm_profiles JSONB NOT NULL,
                        embedding_profiles JSONB NOT NULL,
                        execution_intent TEXT NOT NULL DEFAULT 'local_first',
                        routing_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
                        concurrency_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
                        assignments JSONB NOT NULL,
                        prompt_catalog JSONB NOT NULL DEFAULT '{}'::jsonb,
                        competitive_intelligence_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS target_users TEXT NOT NULL DEFAULT ''")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS goals JSONB NOT NULL DEFAULT '[]'::jsonb")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS preferred_directions JSONB NOT NULL DEFAULT '[]'::jsonb")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS rejected_directions JSONB NOT NULL DEFAULT '[]'::jsonb")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft'")
                cursor.execute("ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS execution_intent TEXT NOT NULL DEFAULT 'local_first'")
                cursor.execute("ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS routing_policy JSONB NOT NULL DEFAULT '{}'::jsonb")
                cursor.execute("ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS concurrency_policy JSONB NOT NULL DEFAULT '{}'::jsonb")
                cursor.execute("ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS prompt_catalog JSONB NOT NULL DEFAULT '{}'::jsonb")
                cursor.execute("ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS competitive_intelligence_enabled BOOLEAN NOT NULL DEFAULT TRUE")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS brief_conversations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        request_id TEXT,
                        extracted_updates JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_telemetry_settings (
                        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        capture_prompt_bodies BOOLEAN NOT NULL DEFAULT TRUE,
                        capture_response_bodies BOOLEAN NOT NULL DEFAULT TRUE,
                        capture_parsed_results BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS model_call_events (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        layer TEXT NOT NULL,
                        workflow TEXT NOT NULL,
                        run_id TEXT,
                        request_kind TEXT NOT NULL,
                        provider_kind TEXT NOT NULL,
                        model_name TEXT,
                        model_profile_id TEXT,
                        prompt_key TEXT,
                        prompt_version TEXT,
                        status TEXT NOT NULL,
                        attempt INTEGER NOT NULL DEFAULT 1,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        latency_ms INTEGER NOT NULL DEFAULT 0,
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        estimated_cost_usd DOUBLE PRECISION,
                        request_chars INTEGER NOT NULL DEFAULT 0,
                        response_chars INTEGER NOT NULL DEFAULT 0,
                        system_prompt TEXT,
                        user_prompt TEXT,
                        raw_response TEXT,
                        parsed_result JSONB NOT NULL DEFAULT '{}'::jsonb,
                        error_type TEXT,
                        error_message TEXT,
                        started_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS nodes (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        parent_id TEXT REFERENCES nodes(id) ON DELETE CASCADE,
                        layer INTEGER NOT NULL,
                        node_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT,
                        json_payload JSONB,
                        status TEXT DEFAULT 'generated',
                        priority INTEGER,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS generations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        node_id TEXT REFERENCES nodes(id) ON DELETE SET NULL,
                        prompt TEXT NOT NULL,
                        raw_response TEXT NOT NULL,
                        parsed_json JSONB,
                        model_name TEXT,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_memory (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        memory_type TEXT NOT NULL,
                        content JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS node_embeddings (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                        embedding_model TEXT NOT NULL,
                        embedding vector(384) NOT NULL,
                        content_hash TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_jobs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        job_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL,
                        details JSONB NOT NULL,
                        error TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS platform_jobs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        kind TEXT NOT NULL,
                        workflow TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL,
                        current_step TEXT NOT NULL DEFAULT '',
                        request_payload JSONB NOT NULL,
                        result_payload JSONB NOT NULL,
                        error_type TEXT,
                        error_message TEXT,
                        dedupe_key TEXT,
                        cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
                        attempt INTEGER NOT NULL DEFAULT 1,
                        created_at TIMESTAMPTZ NOT NULL,
                        started_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_sources (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        competitor_name TEXT NOT NULL,
                        domain TEXT NOT NULL,
                        url TEXT NOT NULL,
                        page_type TEXT NOT NULL,
                        title TEXT,
                        status_code INTEGER,
                        fetched_at TIMESTAMPTZ NOT NULL,
                        content_hash TEXT,
                        metadata JSONB NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_chunks (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        source_id TEXT NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
                        competitor_name TEXT NOT NULL,
                        domain TEXT NOT NULL,
                        url TEXT NOT NULL,
                        title TEXT,
                        chunk_index INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        embedding vector(384) NOT NULL,
                        metadata JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_findings (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        finding_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer1_pillars (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        node_id TEXT NOT NULL UNIQUE REFERENCES nodes(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_generation_runs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        source_pillar_ids JSONB NOT NULL,
                        lenses JSONB NOT NULL,
                        source_model TEXT NOT NULL,
                        status TEXT NOT NULL,
                        summary JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_raw_candidates (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        generation_run_id TEXT NOT NULL REFERENCES layer2_generation_runs(id) ON DELETE CASCADE,
                        source_pillar_id TEXT NOT NULL,
                        source_lens TEXT NOT NULL,
                        source_model TEXT NOT NULL,
                        generation_round INTEGER NOT NULL,
                        raw_text TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        negative_cache_match BOOLEAN NOT NULL DEFAULT FALSE,
                        negative_cache_reason TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_features (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        canonical_name TEXT NOT NULL,
                        description TEXT NOT NULL,
                        feature_type TEXT NOT NULL,
                        granularity_class TEXT NOT NULL DEFAULT 'feature',
                        owner_pillar_id TEXT NOT NULL,
                        candidate_source_ids JSONB NOT NULL,
                        aliases JSONB NOT NULL,
                        status TEXT NOT NULL,
                        related_pillar_ids JSONB NOT NULL,
                        used_by_feature_ids JSONB NOT NULL,
                        depends_on_feature_ids JSONB NOT NULL,
                        specificity_score INTEGER NOT NULL,
                        pillar_fit_score INTEGER NOT NULL,
                        distinctiveness_score INTEGER NOT NULL,
                        implementation_leakage_score INTEGER NOT NULL,
                        strategic_value_score INTEGER NOT NULL,
                        needs_human_review BOOLEAN NOT NULL,
                        metadata JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_workspace_state (
                        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                        view_mode TEXT NOT NULL DEFAULT 'map',
                        selected_entity_type TEXT NOT NULL DEFAULT 'brief',
                        selected_entity_id TEXT NOT NULL DEFAULT 'layer0-root',
                        table_scope TEXT NOT NULL DEFAULT 'focused',
                        map_state JSONB NOT NULL DEFAULT '{}'::jsonb,
                        table_state JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_capability_cards (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        feature_id TEXT NOT NULL,
                        parent_pillar_id TEXT NOT NULL,
                        parent_pillar_title TEXT NOT NULL,
                        feature_name TEXT NOT NULL,
                        feature_description TEXT NOT NULL DEFAULT '',
                        product_purpose TEXT NOT NULL,
                        feature_archetype TEXT NOT NULL,
                        supported_variants JSONB NOT NULL,
                        configurable_options JSONB NOT NULL,
                        product_behaviors JSONB NOT NULL,
                        validation_constraints JSONB NOT NULL,
                        lifecycle_states JSONB NOT NULL,
                        dependencies JSONB NOT NULL,
                        overlaps_conflicts JSONB NOT NULL,
                        edge_cases JSONB NOT NULL,
                        product_risks JSONB NOT NULL,
                        pressure_test JSONB NOT NULL,
                        downstream_readiness_score INTEGER NOT NULL,
                        readiness_rationale TEXT NOT NULL,
                        review_state TEXT NOT NULL,
                        provenance JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(project_id, feature_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_relationships (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        card_id TEXT NOT NULL REFERENCES layer3_capability_cards(id) ON DELETE CASCADE,
                        source_feature_id TEXT NOT NULL,
                        target_feature_id TEXT NOT NULL,
                        relationship_type TEXT NOT NULL,
                        rationale TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_open_decisions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        card_id TEXT NOT NULL REFERENCES layer3_capability_cards(id) ON DELETE CASCADE,
                        question TEXT NOT NULL,
                        context TEXT NOT NULL DEFAULT '',
                        options JSONB NOT NULL,
                        status TEXT NOT NULL,
                        resolution TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_review_actions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        card_id TEXT NOT NULL REFERENCES layer3_capability_cards(id) ON DELETE CASCADE,
                        action_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute("ALTER TABLE brief_conversations ADD COLUMN IF NOT EXISTS request_id TEXT")
                cursor.execute("ALTER TABLE layer2_features ADD COLUMN IF NOT EXISTS granularity_class TEXT NOT NULL DEFAULT 'feature'")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_feature_aliases (
                        id TEXT PRIMARY KEY,
                        feature_id TEXT NOT NULL REFERENCES layer2_features(id) ON DELETE CASCADE,
                        alias TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(feature_id, alias)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_feature_relationships (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        source_feature_id TEXT NOT NULL,
                        target_feature_id TEXT NOT NULL,
                        relationship_type TEXT NOT NULL,
                        strength DOUBLE PRECISION NOT NULL,
                        rationale TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_pillar_affinity (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        feature_id TEXT NOT NULL,
                        pillar_id TEXT NOT NULL,
                        affinity_score DOUBLE PRECISION NOT NULL,
                        recommended_owner_pillar_id TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_negative_cache (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        rejected_name TEXT NOT NULL,
                        semantic_cluster TEXT NOT NULL,
                        rejected_aliases JSONB NOT NULL,
                        rejected_at_layer INTEGER NOT NULL,
                        rejected_from_pillar_id TEXT NOT NULL,
                        embedding_model TEXT NOT NULL DEFAULT '',
                        embedding vector(384),
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute("ALTER TABLE layer2_negative_cache ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT ''")
                cursor.execute("ALTER TABLE layer2_negative_cache ADD COLUMN IF NOT EXISTS embedding vector(384)")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_coverage_matrix (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        pillar_id TEXT NOT NULL,
                        family_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        evidence_feature_ids JSONB NOT NULL,
                        missing_examples JSONB NOT NULL,
                        last_lens_run TEXT NOT NULL DEFAULT '',
                        drift_flags BOOLEAN NOT NULL DEFAULT FALSE,
                        ambiguity_flags BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(project_id, pillar_id, family_name)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_shared_concern_clusters (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        concern_type TEXT NOT NULL,
                        connected_feature_ids JSONB NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(project_id, name, concern_type)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_feature_evidence (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        feature_id TEXT NOT NULL REFERENCES layer2_features(id) ON DELETE CASCADE,
                        competitor_name TEXT NOT NULL,
                        coverage_status TEXT NOT NULL,
                        confidence INTEGER NOT NULL,
                        source_url TEXT NOT NULL DEFAULT '',
                        evidence_snippet TEXT NOT NULL DEFAULT '',
                        rationale TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        source_type TEXT NOT NULL DEFAULT 'manual',
                        research_job_id TEXT REFERENCES research_jobs(id) ON DELETE SET NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute("ALTER TABLE layer2_feature_evidence ADD COLUMN IF NOT EXISTS rationale TEXT NOT NULL DEFAULT ''")
                cursor.execute("ALTER TABLE layer2_feature_evidence ADD COLUMN IF NOT EXISTS research_job_id TEXT")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_competitive_settings (
                        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                        known_competitors JSONB NOT NULL,
                        research_mode TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer2_review_actions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        feature_id TEXT,
                        action_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_project_memory_scope
                    ON project_memory(project_id, scope, COALESCE(scope_id, ''), memory_type)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_nodes_project_parent_layer_type
                    ON nodes(project_id, COALESCE(parent_id, ''), layer, node_type)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_brief_conversations_project_created
                    ON brief_conversations(project_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assistant_conversations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        title TEXT NOT NULL,
                        home_scope TEXT NOT NULL,
                        compacted_summary TEXT NOT NULL DEFAULT '',
                        summary_state JSONB NOT NULL DEFAULT '{}'::jsonb,
                        archived BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assistant_messages (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL,
                        request_id TEXT,
                        active_scope TEXT NOT NULL,
                        focus JSONB NOT NULL,
                        reference_conversation_ids JSONB NOT NULL,
                        execution_intent_override TEXT,
                        thinking_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        deep_mode BOOLEAN NOT NULL DEFAULT FALSE,
                        citations JSONB NOT NULL,
                        proposed_actions JSONB NOT NULL,
                        retrieval_trace JSONB NOT NULL,
                        error TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assistant_documents (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        layer_scope TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        metadata JSONB NOT NULL,
                        embedding_model TEXT NOT NULL DEFAULT '',
                        embedding vector(384),
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(project_id, source_type, source_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assistant_runs (
                        id TEXT PRIMARY KEY,
                        assistant_message_id TEXT NOT NULL UNIQUE REFERENCES assistant_messages(id) ON DELETE CASCADE,
                        runtime_kind TEXT NOT NULL,
                        model_profile_id TEXT NOT NULL,
                        execution_intent TEXT NOT NULL DEFAULT 'local_first',
                        effective_parallelism INTEGER NOT NULL DEFAULT 1,
                        status TEXT NOT NULL,
                        planned_tools JSONB NOT NULL,
                        specialist_plan JSONB NOT NULL,
                        error TEXT,
                        started_at TIMESTAMPTZ,
                        completed_at TIMESTAMPTZ
                    )
                    """
                )
                cursor.execute("ALTER TABLE assistant_messages ADD COLUMN IF NOT EXISTS execution_intent_override TEXT")
                cursor.execute("ALTER TABLE assistant_runs ADD COLUMN IF NOT EXISTS execution_intent TEXT NOT NULL DEFAULT 'local_first'")
                cursor.execute("ALTER TABLE assistant_runs ADD COLUMN IF NOT EXISTS effective_parallelism INTEGER NOT NULL DEFAULT 1")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assistant_specialist_runs (
                        id TEXT PRIMARY KEY,
                        assistant_run_id TEXT NOT NULL REFERENCES assistant_runs(id) ON DELETE CASCADE,
                        specialist_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        input_payload JSONB NOT NULL,
                        output_payload JSONB NOT NULL,
                        error TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assistant_action_proposals (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        conversation_id TEXT NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
                        message_id TEXT NOT NULL REFERENCES assistant_messages(id) ON DELETE CASCADE,
                        action_type TEXT NOT NULL,
                        label TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        expected_state JSONB NOT NULL,
                        status TEXT NOT NULL,
                        result JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_brief_conversations_request_role
                    ON brief_conversations(project_id, request_id, role)
                    WHERE request_id IS NOT NULL
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_nodes_project_status
                    ON nodes(project_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_app_settings_key
                    ON app_settings(key)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_project_model_settings_project
                    ON project_model_settings(project_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_generations_project_node
                    ON generations(project_id, node_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_node_embeddings_project_node
                    ON node_embeddings(project_id, node_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_node_embeddings_node_model
                    ON node_embeddings(node_id, embedding_model)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_jobs_project_scope
                    ON research_jobs(project_id, scope, COALESCE(scope_id, ''), updated_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_platform_jobs_project_updated
                    ON platform_jobs(project_id, updated_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_platform_jobs_dedupe
                    ON platform_jobs(project_id, dedupe_key, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_sources_project_scope
                    ON research_sources(project_id, scope, COALESCE(scope_id, ''), fetched_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_findings_project_scope
                    ON research_findings(project_id, scope, COALESCE(scope_id, ''), updated_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_chunks_project_scope
                    ON research_chunks(project_id, scope, COALESCE(scope_id, ''), source_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_features_project_owner
                    ON layer2_features(project_id, owner_pillar_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_raw_candidates_run
                    ON layer2_raw_candidates(project_id, generation_run_id, source_pillar_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_relationships_project
                    ON layer2_feature_relationships(project_id, source_feature_id, target_feature_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_review_project
                    ON layer2_review_actions(project_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_coverage_matrix_pillar
                    ON layer2_coverage_matrix(project_id, pillar_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_shared_concern_project
                    ON layer2_shared_concern_clusters(project_id, concern_type, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_feature_evidence_feature
                    ON layer2_feature_evidence(project_id, feature_id, competitor_name)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer3_cards_project_review
                    ON layer3_capability_cards(project_id, review_state, feature_name)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer3_relationships_card
                    ON layer3_relationships(card_id, relationship_type)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer3_decisions_card
                    ON layer3_open_decisions(card_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_model_call_events_project_started
                    ON model_call_events(project_id, started_at DESC)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_model_call_events_project_layer
                    ON model_call_events(project_id, layer, workflow)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_assistant_conversations_project
                    ON assistant_conversations(project_id, archived, updated_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_assistant_messages_conversation
                    ON assistant_messages(conversation_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_assistant_message_request_role
                    ON assistant_messages(conversation_id, request_id, role)
                    WHERE request_id IS NOT NULL
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_assistant_documents_project_scope
                    ON assistant_documents(project_id, layer_scope, source_type)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer2_negative_cache_vector
                    ON layer2_negative_cache USING ivfflat (embedding vector_cosine_ops)
                    WHERE embedding IS NOT NULL
                    """
                )


