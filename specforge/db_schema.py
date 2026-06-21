from __future__ import annotations


class DatabaseSchemaMixin:
    """Schema creation routines for SQLite and PostgreSQL backends."""

    def _initialize_sqlite(self) -> None:
        """Create the SQLite schema used by tests and legacy local setups."""
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    idea TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_briefs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE,
                    product_idea TEXT NOT NULL,
                    known_competitors TEXT NOT NULL,
                    constraints TEXT NOT NULL,
                    target_users TEXT NOT NULL DEFAULT '',
                    goals TEXT NOT NULL DEFAULT '[]',
                    preferred_directions TEXT NOT NULL DEFAULT '[]',
                    rejected_directions TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_model_settings (
                    project_id TEXT PRIMARY KEY,
                    llm_profiles TEXT NOT NULL,
                    embedding_profiles TEXT NOT NULL,
                    assignments TEXT NOT NULL,
                    prompt_catalog TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS brief_conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    extracted_updates TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    parent_id TEXT,
                    layer INTEGER NOT NULL,
                    node_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    json_payload TEXT,
                    status TEXT DEFAULT 'generated',
                    priority INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(parent_id) REFERENCES nodes(id)
                );

                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    node_id TEXT,
                    prompt TEXT NOT NULL,
                    raw_response TEXT NOT NULL,
                    parsed_json TEXT,
                    model_name TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_memory (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    details TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS research_sources (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    competitor_name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    page_type TEXT NOT NULL,
                    title TEXT,
                    status_code INTEGER,
                    fetched_at TEXT NOT NULL,
                    content_hash TEXT,
                    metadata TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS research_chunks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    source_id TEXT NOT NULL,
                    competitor_name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(source_id) REFERENCES research_sources(id)
                );

                CREATE TABLE IF NOT EXISTS research_findings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    finding_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer1_pillars (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    node_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(node_id) REFERENCES nodes(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_generation_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_pillar_ids TEXT NOT NULL,
                    lenses TEXT NOT NULL,
                    source_model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_raw_candidates (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    generation_run_id TEXT NOT NULL,
                    source_pillar_id TEXT NOT NULL,
                    source_lens TEXT NOT NULL,
                    source_model TEXT NOT NULL,
                    generation_round INTEGER NOT NULL,
                    raw_text TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    negative_cache_match INTEGER NOT NULL DEFAULT 0,
                    negative_cache_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(generation_run_id) REFERENCES layer2_generation_runs(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_features (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    feature_type TEXT NOT NULL,
                    granularity_class TEXT NOT NULL DEFAULT 'feature',
                    owner_pillar_id TEXT NOT NULL,
                    candidate_source_ids TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    status TEXT NOT NULL,
                    related_pillar_ids TEXT NOT NULL,
                    used_by_feature_ids TEXT NOT NULL,
                    depends_on_feature_ids TEXT NOT NULL,
                    specificity_score INTEGER NOT NULL,
                    pillar_fit_score INTEGER NOT NULL,
                    distinctiveness_score INTEGER NOT NULL,
                    implementation_leakage_score INTEGER NOT NULL,
                    strategic_value_score INTEGER NOT NULL,
                    needs_human_review INTEGER NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_feature_aliases (
                    id TEXT PRIMARY KEY,
                    feature_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(feature_id, alias),
                    FOREIGN KEY(feature_id) REFERENCES layer2_features(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_feature_relationships (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_feature_id TEXT NOT NULL,
                    target_feature_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    strength REAL NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_pillar_affinity (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    feature_id TEXT NOT NULL,
                    pillar_id TEXT NOT NULL,
                    affinity_score REAL NOT NULL,
                    recommended_owner_pillar_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_negative_cache (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    rejected_name TEXT NOT NULL,
                    semantic_cluster TEXT NOT NULL,
                    rejected_aliases TEXT NOT NULL,
                    rejected_at_layer INTEGER NOT NULL,
                    rejected_from_pillar_id TEXT NOT NULL,
                    embedding_model TEXT NOT NULL DEFAULT '',
                    embedding TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_coverage_matrix (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    pillar_id TEXT NOT NULL,
                    family_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    evidence_feature_ids TEXT NOT NULL,
                    missing_examples TEXT NOT NULL,
                    last_lens_run TEXT NOT NULL DEFAULT '',
                    drift_flags INTEGER NOT NULL DEFAULT 0,
                    ambiguity_flags INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, pillar_id, family_name),
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_shared_concern_clusters (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    concern_type TEXT NOT NULL,
                    connected_feature_ids TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, name, concern_type),
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_feature_evidence (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    feature_id TEXT NOT NULL,
                    competitor_name TEXT NOT NULL,
                    coverage_status TEXT NOT NULL,
                    confidence INTEGER NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    evidence_snippet TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(feature_id) REFERENCES layer2_features(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_competitive_settings (
                    project_id TEXT PRIMARY KEY,
                    known_competitors TEXT NOT NULL,
                    research_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS layer2_review_actions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    feature_id TEXT,
                    action_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_project_memory_scope
                ON project_memory(project_id, scope, COALESCE(scope_id, ''), memory_type);

                CREATE INDEX IF NOT EXISTS idx_nodes_project_parent_layer_type
                ON nodes(project_id, COALESCE(parent_id, ''), layer, node_type);

                CREATE INDEX IF NOT EXISTS idx_brief_conversations_project_created
                ON brief_conversations(project_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_nodes_project_status
                ON nodes(project_id, status);

                CREATE INDEX IF NOT EXISTS idx_app_settings_key
                ON app_settings(key);

                CREATE INDEX IF NOT EXISTS idx_project_model_settings_project
                ON project_model_settings(project_id);

                CREATE INDEX IF NOT EXISTS idx_generations_project_node
                ON generations(project_id, node_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_research_jobs_project_scope
                ON research_jobs(project_id, scope, COALESCE(scope_id, ''), updated_at);

                CREATE INDEX IF NOT EXISTS idx_research_sources_project_scope
                ON research_sources(project_id, scope, COALESCE(scope_id, ''), fetched_at);

                CREATE INDEX IF NOT EXISTS idx_research_findings_project_scope
                ON research_findings(project_id, scope, COALESCE(scope_id, ''), updated_at);

                CREATE INDEX IF NOT EXISTS idx_layer2_features_project_owner
                ON layer2_features(project_id, owner_pillar_id, status);

                CREATE INDEX IF NOT EXISTS idx_layer2_raw_candidates_run
                ON layer2_raw_candidates(project_id, generation_run_id, source_pillar_id);

                CREATE INDEX IF NOT EXISTS idx_layer2_relationships_project
                ON layer2_feature_relationships(project_id, source_feature_id, target_feature_id);

                CREATE INDEX IF NOT EXISTS idx_layer2_review_project
                ON layer2_review_actions(project_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_layer2_coverage_matrix_pillar
                ON layer2_coverage_matrix(project_id, pillar_id, status);

                CREATE INDEX IF NOT EXISTS idx_layer2_shared_concern_project
                ON layer2_shared_concern_clusters(project_id, concern_type, status);

                CREATE INDEX IF NOT EXISTS idx_layer2_feature_evidence_feature
                ON layer2_feature_evidence(project_id, feature_id, competitor_name);
                """
            )
        try:
            self._execute(
                "ALTER TABLE project_model_settings ADD COLUMN prompt_catalog TEXT NOT NULL DEFAULT '{}'"
            )
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        for statement in (
            "ALTER TABLE layer2_features ADD COLUMN granularity_class TEXT NOT NULL DEFAULT 'feature'",
            "ALTER TABLE layer2_negative_cache ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE layer2_negative_cache ADD COLUMN embedding TEXT",
        ):
            try:
                self._execute(statement)
            except Exception as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

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
                        assignments JSONB NOT NULL,
                        prompt_catalog JSONB NOT NULL DEFAULT '{}'::jsonb,
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
                cursor.execute("ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS prompt_catalog JSONB NOT NULL DEFAULT '{}'::jsonb")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS brief_conversations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        extracted_updates JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
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
                        notes TEXT NOT NULL DEFAULT '',
                        source_type TEXT NOT NULL DEFAULT 'manual',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
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
                    CREATE INDEX IF NOT EXISTS idx_layer2_negative_cache_vector
                    ON layer2_negative_cache USING ivfflat (embedding vector_cosine_ops)
                    WHERE embedding IS NOT NULL
                    """
                )


