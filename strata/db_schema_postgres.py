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
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        last_opened_at TIMESTAMPTZ,
                        archived_at TIMESTAMPTZ,
                        lifecycle_state TEXT NOT NULL DEFAULT 'active',
                        source_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL
                    )
                    """
                )
                cursor.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
                cursor.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ")
                cursor.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ")
                cursor.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS lifecycle_state TEXT NOT NULL DEFAULT 'active'")
                cursor.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS source_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL")
                cursor.execute("UPDATE projects SET updated_at = created_at WHERE updated_at IS NULL")
                cursor.execute("UPDATE projects SET lifecycle_state = 'active' WHERE lifecycle_state IS NULL OR lifecycle_state = ''")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_briefs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
                        product_idea TEXT NOT NULL,
                        problem TEXT NOT NULL DEFAULT '',
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
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS problem TEXT NOT NULL DEFAULT ''")
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
                    CREATE TABLE IF NOT EXISTS project_data_ownership_settings (
                        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                        telemetry_retention_days INTEGER,
                        telemetry_body_retention_days INTEGER,
                        research_retention_days INTEGER,
                        assistant_retention_days INTEGER,
                        exports_retention_days INTEGER,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute("ALTER TABLE project_data_ownership_settings ADD COLUMN IF NOT EXISTS telemetry_retention_days INTEGER")
                cursor.execute("ALTER TABLE project_data_ownership_settings ADD COLUMN IF NOT EXISTS telemetry_body_retention_days INTEGER")
                cursor.execute("ALTER TABLE project_data_ownership_settings ADD COLUMN IF NOT EXISTS research_retention_days INTEGER")
                cursor.execute("ALTER TABLE project_data_ownership_settings ADD COLUMN IF NOT EXISTS assistant_retention_days INTEGER")
                cursor.execute("ALTER TABLE project_data_ownership_settings ADD COLUMN IF NOT EXISTS exports_retention_days INTEGER")
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
                    CREATE TABLE IF NOT EXISTS layer3_feature_expansions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        feature_id TEXT NOT NULL,
                        parent_pillar_id TEXT NOT NULL,
                        parent_pillar_title TEXT NOT NULL,
                        feature_name TEXT NOT NULL,
                        feature_description TEXT NOT NULL DEFAULT '',
                        feature_intent TEXT NOT NULL,
                        expansion_groups JSONB NOT NULL,
                        overlap_review JSONB NOT NULL,
                        open_questions JSONB NOT NULL,
                        review_state TEXT NOT NULL,
                        provenance JSONB NOT NULL,
                        active_revision_id TEXT NOT NULL DEFAULT '',
                        revision_number INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(project_id, feature_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_expansion_actions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        expansion_id TEXT NOT NULL REFERENCES layer3_feature_expansions(id) ON DELETE CASCADE,
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
                    CREATE TABLE IF NOT EXISTS layer2_feature_embeddings (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        feature_id TEXT NOT NULL REFERENCES layer2_features(id) ON DELETE CASCADE,
                        embedding_model TEXT NOT NULL,
                        embedding vector(384) NOT NULL,
                        content_hash TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(feature_id, embedding_model)
                    )
                    """
                )
                cursor.execute("ALTER TABLE layer3_feature_expansions ADD COLUMN IF NOT EXISTS active_revision_id TEXT NOT NULL DEFAULT ''")
                cursor.execute("ALTER TABLE layer3_feature_expansions ADD COLUMN IF NOT EXISTS revision_number INTEGER NOT NULL DEFAULT 0")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_expansion_heads (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        feature_id TEXT NOT NULL REFERENCES layer2_features(id) ON DELETE CASCADE,
                        active_revision_id TEXT,
                        next_revision_number INTEGER NOT NULL DEFAULT 1 CHECK (next_revision_number >= 1),
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(project_id, feature_id),
                        CONSTRAINT layer3_heads_id_project_unique UNIQUE(id, project_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_expansion_revisions (
                        id TEXT PRIMARY KEY,
                        logical_expansion_id TEXT NOT NULL,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        revision_number INTEGER NOT NULL,
                        source_layer2_feature_revision TEXT NOT NULL DEFAULT '',
                        source_brief_revision TEXT NOT NULL DEFAULT '',
                        source_pillar_revision TEXT NOT NULL DEFAULT '',
                        generation_reference TEXT NOT NULL DEFAULT '',
                        origin TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        structured_diff JSONB NOT NULL,
                        field_ownership JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(logical_expansion_id, revision_number),
                        CONSTRAINT layer3_revisions_logical_id_unique UNIQUE(logical_expansion_id, id),
                        CONSTRAINT layer3_revisions_head_project_fk FOREIGN KEY (logical_expansion_id, project_id)
                            REFERENCES layer3_expansion_heads(id, project_id) ON DELETE CASCADE,
                        CHECK (revision_number >= 1)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_expansion_revision_states (
                        revision_id TEXT PRIMARY KEY REFERENCES layer3_expansion_revisions(id) ON DELETE CASCADE,
                        logical_expansion_id TEXT NOT NULL REFERENCES layer3_expansion_heads(id) ON DELETE CASCADE,
                        workflow_state TEXT NOT NULL,
                        review_state TEXT NOT NULL,
                        freshness_state TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        active_slot INTEGER GENERATED ALWAYS AS (
                            CASE WHEN workflow_state = 'active' THEN 1 ELSE NULL END
                        ) STORED,
                        CONSTRAINT layer3_revision_states_revision_owner_fk FOREIGN KEY (logical_expansion_id, revision_id)
                            REFERENCES layer3_expansion_revisions(logical_expansion_id, id) ON DELETE CASCADE,
                        CONSTRAINT layer3_revision_states_workflow_check
                            CHECK (workflow_state IN ('candidate', 'active', 'superseded', 'rejected', 'applied_partial')),
                        CONSTRAINT layer3_revision_states_review_check
                            CHECK (review_state IN ('draft', 'approved', 'rejected', 'needs_review')),
                        CONSTRAINT layer3_revision_states_freshness_check
                            CHECK (freshness_state IN ('fresh', 'stale', 'unknown')),
                        CONSTRAINT layer3_revision_states_consistency_check CHECK (
                            (workflow_state <> 'candidate' OR review_state = 'needs_review')
                            AND (workflow_state <> 'rejected' OR review_state = 'rejected')
                            AND (workflow_state <> 'applied_partial' OR review_state = 'approved')
                        ),
                        CONSTRAINT layer3_revision_states_one_active
                            UNIQUE (logical_expansion_id, active_slot) DEFERRABLE INITIALLY DEFERRED
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layer3_revision_actions (
                        id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL UNIQUE,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        logical_expansion_id TEXT NOT NULL,
                        revision_id TEXT,
                        action_type TEXT NOT NULL,
                        expected_active_revision_id TEXT,
                        previous_active_revision_id TEXT,
                        new_active_revision_id TEXT,
                        selected_sections JSONB NOT NULL,
                        before_snapshot JSONB NOT NULL,
                        after_snapshot JSONB NOT NULL,
                        actor TEXT NOT NULL,
                        origin TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        CONSTRAINT layer3_revision_actions_head_project_fk FOREIGN KEY (logical_expansion_id, project_id)
                            REFERENCES layer3_expansion_heads(id, project_id) ON DELETE CASCADE,
                        CONSTRAINT layer3_revision_actions_revision_owner_fk FOREIGN KEY (logical_expansion_id, revision_id)
                            REFERENCES layer3_expansion_revisions(logical_expansion_id, id) ON DELETE CASCADE
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS overlap_job_items (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        job_id TEXT NOT NULL REFERENCES platform_jobs(id) ON DELETE CASCADE,
                        layer TEXT NOT NULL,
                        item_id TEXT NOT NULL,
                        item_hash TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL,
                        error TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        UNIQUE(job_id, item_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS overlap_verdicts (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        job_id TEXT NOT NULL REFERENCES platform_jobs(id) ON DELETE CASCADE,
                        layer TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        neighbor_id TEXT NOT NULL,
                        relation TEXT NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        rationale TEXT NOT NULL DEFAULT '',
                        critic_source TEXT NOT NULL DEFAULT 'overlap_critic',
                        target_hash TEXT NOT NULL DEFAULT '',
                        neighbor_hash TEXT NOT NULL DEFAULT '',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS overlap_clusters (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        job_id TEXT NOT NULL REFERENCES platform_jobs(id) ON DELETE CASCADE,
                        layer TEXT NOT NULL,
                        cluster_id TEXT NOT NULL,
                        member_ids JSONB NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS overlap_verdict_resolutions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        verdict_id TEXT NOT NULL REFERENCES overlap_verdicts(id) ON DELETE CASCADE,
                        layer TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        neighbor_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        note TEXT NOT NULL DEFAULT '',
                        resolved_by TEXT NOT NULL DEFAULT 'user',
                        target_hash TEXT NOT NULL DEFAULT '',
                        neighbor_hash TEXT NOT NULL DEFAULT '',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
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
                    CREATE TABLE IF NOT EXISTS artifact_authority_actions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        artifact_type TEXT NOT NULL CHECK (artifact_type IN ('layer1_pillar', 'layer2_feature', 'layer3_expansion')),
                        artifact_id TEXT NOT NULL,
                        revision_id TEXT NOT NULL DEFAULT '',
                        action_type TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        origin TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS critic_findings (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        artifact_type TEXT NOT NULL CHECK (artifact_type IN ('layer1_pillar', 'layer2_feature', 'layer3_expansion')),
                        artifact_id TEXT NOT NULL,
                        artifact_revision_id TEXT NOT NULL DEFAULT '',
                        critic_type TEXT NOT NULL,
                        policy_version TEXT NOT NULL,
                        category TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        explanation TEXT NOT NULL,
                        evidence JSONB NOT NULL,
                        recommended_action TEXT NOT NULL,
                        source_fingerprint TEXT NOT NULL,
                        model_reference TEXT NOT NULL DEFAULT '',
                        job_reference TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL CHECK (status IN ('open', 'accepted', 'dismissed', 'superseded')),
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        resolution_action TEXT NOT NULL DEFAULT '',
                        resolution_note TEXT NOT NULL DEFAULT '',
                        resolved_by TEXT NOT NULL DEFAULT '',
                        resolved_at TIMESTAMPTZ,
                        CHECK ((status = 'open' AND resolved_at IS NULL) OR (status <> 'open' AND resolved_at IS NOT NULL)),
                        UNIQUE(project_id, artifact_type, artifact_id, artifact_revision_id, critic_type, policy_version, category, source_fingerprint)
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS command_executions (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        command_type TEXT NOT NULL,
                        target_type TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        actor_type TEXT NOT NULL CHECK (actor_type IN ('human', 'system', 'import', 'migration', 'model')),
                        origin TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        request_fingerprint TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('running', 'completed')),
                        input_payload JSONB NOT NULL,
                        result_payload JSONB NOT NULL,
                        stale_effects JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        completed_at TIMESTAMPTZ,
                        UNIQUE(project_id, idempotency_key)
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
                    CREATE INDEX IF NOT EXISTS idx_layer2_feature_embeddings_project
                    ON layer2_feature_embeddings(project_id, feature_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_overlap_verdicts_project_layer
                    ON overlap_verdicts(project_id, layer, job_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_overlap_job_items_job
                    ON overlap_job_items(job_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_overlap_clusters_project_layer
                    ON overlap_clusters(project_id, layer, job_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_overlap_resolutions_pair
                    ON overlap_verdict_resolutions(project_id, layer, target_id, neighbor_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_overlap_resolutions_verdict
                    ON overlap_verdict_resolutions(verdict_id, created_at)
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
                    CREATE INDEX IF NOT EXISTS idx_artifact_authority_lookup
                    ON artifact_authority_actions(project_id, artifact_type, artifact_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_critic_findings_project
                    ON critic_findings(project_id, artifact_type, artifact_id, status, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_command_executions_target
                    ON command_executions(project_id, target_type, target_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION strata_cleanup_critic_records() RETURNS trigger AS $$
                    DECLARE target_type TEXT;
                    BEGIN
                        target_type := TG_ARGV[0];
                        DELETE FROM critic_findings WHERE artifact_type = target_type AND artifact_id = OLD.id;
                        DELETE FROM artifact_authority_actions WHERE artifact_type = target_type AND artifact_id = OLD.id;
                        RETURN OLD;
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
                for table, trigger, artifact_type in (
                    ("nodes", "cleanup_node_critic_records", "layer1_pillar"),
                    ("layer2_features", "cleanup_layer2_critic_records", "layer2_feature"),
                    ("layer3_expansion_heads", "cleanup_layer3_critic_records", "layer3_expansion"),
                ):
                    cursor.execute("SELECT 1 FROM pg_trigger WHERE tgname = %s", (trigger,))
                    if cursor.fetchone() is None:
                        cursor.execute(
                            f"CREATE TRIGGER {trigger} AFTER DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION strata_cleanup_critic_records('{artifact_type}')"
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
                    CREATE INDEX IF NOT EXISTS idx_layer3_expansions_project_review
                    ON layer3_feature_expansions(project_id, review_state, feature_name)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer3_expansion_actions_expansion
                    ON layer3_expansion_actions(expansion_id, action_type)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer3_revisions_logical_number
                    ON layer3_expansion_revisions(logical_expansion_id, revision_number)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_layer3_revision_actions_logical
                    ON layer3_revision_actions(logical_expansion_id, created_at)
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


