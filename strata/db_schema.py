from __future__ import annotations

from strata.db_schema_postgres import PostgresSchemaMixin


class DatabaseSchemaMixin(PostgresSchemaMixin):
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
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_opened_at TEXT,
                    archived_at TEXT,
                    lifecycle_state TEXT NOT NULL DEFAULT 'active',
                    source_project_id TEXT,
                    FOREIGN KEY(source_project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS project_briefs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE,
                    product_idea TEXT NOT NULL,
                    problem TEXT NOT NULL DEFAULT '',
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
                    execution_intent TEXT NOT NULL DEFAULT 'local_first',
                    routing_policy TEXT NOT NULL DEFAULT '{}',
                    concurrency_policy TEXT NOT NULL DEFAULT '{}',
                    assignments TEXT NOT NULL,
                    prompt_catalog TEXT NOT NULL DEFAULT '{}',
                    competitive_intelligence_enabled INTEGER NOT NULL DEFAULT 1,
                    discovery_settings TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS project_workspace_state (
                    project_id TEXT PRIMARY KEY,
                    view_mode TEXT NOT NULL DEFAULT 'map',
                    selected_entity_type TEXT NOT NULL DEFAULT 'brief',
                    selected_entity_id TEXT NOT NULL DEFAULT 'layer0-root',
                    table_scope TEXT NOT NULL DEFAULT 'focused',
                    map_state TEXT NOT NULL DEFAULT '{}',
                    table_state TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS project_telemetry_settings (
                    project_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    capture_prompt_bodies INTEGER NOT NULL DEFAULT 1,
                    capture_response_bodies INTEGER NOT NULL DEFAULT 1,
                    capture_parsed_results INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS project_data_ownership_settings (
                    project_id TEXT PRIMARY KEY,
                    telemetry_retention_days INTEGER,
                    telemetry_body_retention_days INTEGER,
                    research_retention_days INTEGER,
                    assistant_retention_days INTEGER,
                    exports_retention_days INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS model_call_events (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
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
                    estimated_cost_usd REAL,
                    request_chars INTEGER NOT NULL DEFAULT 0,
                    response_chars INTEGER NOT NULL DEFAULT 0,
                    system_prompt TEXT,
                    user_prompt TEXT,
                    raw_response TEXT,
                    parsed_result TEXT NOT NULL DEFAULT '{}',
                    error_type TEXT,
                    error_message TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS brief_conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    request_id TEXT,
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

                CREATE TABLE IF NOT EXISTS platform_jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    current_step TEXT NOT NULL DEFAULT '',
                    request_payload TEXT NOT NULL,
                    result_payload TEXT NOT NULL,
                    error_type TEXT,
                    error_message TEXT,
                    dedupe_key TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
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

                CREATE TABLE IF NOT EXISTS layer2_feature_embeddings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    feature_id TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding TEXT,
                    content_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(feature_id, embedding_model),
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(feature_id) REFERENCES layer2_features(id)
                );

                CREATE TABLE IF NOT EXISTS overlap_job_items (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    item_hash TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, item_id),
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(job_id) REFERENCES platform_jobs(id)
                );

                CREATE TABLE IF NOT EXISTS overlap_verdicts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    neighbor_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    critic_source TEXT NOT NULL DEFAULT 'overlap_critic',
                    target_hash TEXT NOT NULL DEFAULT '',
                    neighbor_hash TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(job_id) REFERENCES platform_jobs(id)
                );

                CREATE TABLE IF NOT EXISTS overlap_clusters (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    cluster_id TEXT NOT NULL,
                    member_ids TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(job_id) REFERENCES platform_jobs(id)
                );

                CREATE TABLE IF NOT EXISTS overlap_verdict_resolutions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    verdict_id TEXT NOT NULL,
                    layer TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    neighbor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    resolved_by TEXT NOT NULL DEFAULT 'user',
                    target_hash TEXT NOT NULL DEFAULT '',
                    neighbor_hash TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(verdict_id) REFERENCES overlap_verdicts(id)
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
                    rationale TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    research_job_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(feature_id) REFERENCES layer2_features(id),
                    FOREIGN KEY(research_job_id) REFERENCES research_jobs(id)
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

                CREATE TABLE IF NOT EXISTS assistant_conversations (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
                    home_scope TEXT NOT NULL, compacted_summary TEXT NOT NULL DEFAULT '',
                    summary_state TEXT NOT NULL DEFAULT '{}', archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS assistant_messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                    request_id TEXT, active_scope TEXT NOT NULL, focus TEXT NOT NULL,
                    reference_conversation_ids TEXT NOT NULL, execution_intent_override TEXT,
                    thinking_enabled INTEGER NOT NULL DEFAULT 0,
                    deep_mode INTEGER NOT NULL DEFAULT 0, citations TEXT NOT NULL,
                    proposed_actions TEXT NOT NULL, retrieval_trace TEXT NOT NULL, error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(conversation_id) REFERENCES assistant_conversations(id)
                );

                CREATE TABLE IF NOT EXISTS assistant_documents (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, layer_scope TEXT NOT NULL,
                    source_type TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
                    content TEXT NOT NULL, content_hash TEXT NOT NULL, metadata TEXT NOT NULL,
                    embedding_model TEXT NOT NULL DEFAULT '', embedding TEXT, updated_at TEXT NOT NULL,
                    UNIQUE(project_id, source_type, source_id),
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS assistant_runs (
                    id TEXT PRIMARY KEY, assistant_message_id TEXT NOT NULL UNIQUE,
                    runtime_kind TEXT NOT NULL, model_profile_id TEXT NOT NULL, execution_intent TEXT NOT NULL DEFAULT 'local_first',
                    effective_parallelism INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL,
                    planned_tools TEXT NOT NULL, specialist_plan TEXT NOT NULL, error TEXT,
                    started_at TEXT, completed_at TEXT,
                    FOREIGN KEY(assistant_message_id) REFERENCES assistant_messages(id)
                );

                CREATE TABLE IF NOT EXISTS assistant_specialist_runs (
                    id TEXT PRIMARY KEY, assistant_run_id TEXT NOT NULL, specialist_type TEXT NOT NULL,
                    status TEXT NOT NULL, input_payload TEXT NOT NULL, output_payload TEXT NOT NULL,
                    error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(assistant_run_id) REFERENCES assistant_runs(id)
                );

                CREATE TABLE IF NOT EXISTS assistant_action_proposals (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL, action_type TEXT NOT NULL, label TEXT NOT NULL,
                    payload TEXT NOT NULL, expected_state TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(conversation_id) REFERENCES assistant_conversations(id),
                    FOREIGN KEY(message_id) REFERENCES assistant_messages(id)
                );

                CREATE TABLE IF NOT EXISTS layer3_feature_expansions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, feature_id TEXT NOT NULL,
                    parent_pillar_id TEXT NOT NULL, parent_pillar_title TEXT NOT NULL,
                    feature_name TEXT NOT NULL, feature_description TEXT NOT NULL DEFAULT '',
                    feature_intent TEXT NOT NULL, expansion_groups TEXT NOT NULL,
                    overlap_review TEXT NOT NULL, open_questions TEXT NOT NULL,
                    review_state TEXT NOT NULL, provenance TEXT NOT NULL,
                    active_revision_id TEXT NOT NULL DEFAULT '', revision_number INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    UNIQUE(project_id, feature_id)
                );

                CREATE TABLE IF NOT EXISTS artifact_authority_actions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, artifact_type TEXT NOT NULL CHECK (artifact_type IN ('layer1_pillar', 'layer2_feature', 'layer3_expansion')),
                    artifact_id TEXT NOT NULL, revision_id TEXT NOT NULL DEFAULT '', action_type TEXT NOT NULL,
                    actor TEXT NOT NULL, origin TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS critic_findings (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, artifact_type TEXT NOT NULL CHECK (artifact_type IN ('layer1_pillar', 'layer2_feature', 'layer3_expansion')),
                    artifact_id TEXT NOT NULL, artifact_revision_id TEXT NOT NULL DEFAULT '', critic_type TEXT NOT NULL,
                    policy_version TEXT NOT NULL, category TEXT NOT NULL, severity TEXT NOT NULL,
                    explanation TEXT NOT NULL, evidence TEXT NOT NULL, recommended_action TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL, model_reference TEXT NOT NULL DEFAULT '',
                    job_reference TEXT NOT NULL DEFAULT '', status TEXT NOT NULL CHECK (status IN ('open', 'accepted', 'dismissed', 'superseded')), created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, resolution_action TEXT NOT NULL DEFAULT '',
                    resolution_note TEXT NOT NULL DEFAULT '', resolved_by TEXT NOT NULL DEFAULT '', resolved_at TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    CHECK ((status = 'open' AND resolved_at IS NULL) OR (status <> 'open' AND resolved_at IS NOT NULL)),
                    UNIQUE(project_id, artifact_type, artifact_id, artifact_revision_id, critic_type, policy_version, category, source_fingerprint)
                );

                CREATE TABLE IF NOT EXISTS command_executions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, command_type TEXT NOT NULL,
                    target_type TEXT NOT NULL, target_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL CHECK (actor_type IN ('human', 'system', 'import', 'migration', 'model')),
                    origin TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('running', 'completed')),
                    input_payload TEXT NOT NULL, result_payload TEXT NOT NULL, stale_effects TEXT NOT NULL,
                    created_at TEXT NOT NULL, completed_at TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    UNIQUE(project_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS layer3_expansion_actions (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, expansion_id TEXT NOT NULL,
                    action_type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(expansion_id) REFERENCES layer3_feature_expansions(id)
                );

                CREATE TABLE IF NOT EXISTS layer3_expansion_heads (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, feature_id TEXT NOT NULL,
                    active_revision_id TEXT, next_revision_number INTEGER NOT NULL DEFAULT 1 CHECK (next_revision_number >= 1),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(feature_id) REFERENCES layer2_features(id) ON DELETE CASCADE,
                    FOREIGN KEY(id, active_revision_id) REFERENCES layer3_expansion_revisions(logical_expansion_id, id) DEFERRABLE INITIALLY DEFERRED,
                    UNIQUE(project_id, feature_id),
                    UNIQUE(id, project_id)
                );

                CREATE TABLE IF NOT EXISTS layer3_expansion_revisions (
                    id TEXT PRIMARY KEY, logical_expansion_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    revision_number INTEGER NOT NULL, source_layer2_feature_revision TEXT NOT NULL DEFAULT '',
                    source_brief_revision TEXT NOT NULL DEFAULT '', source_pillar_revision TEXT NOT NULL DEFAULT '',
                    generation_reference TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL, actor TEXT NOT NULL,
                    payload TEXT NOT NULL, structured_diff TEXT NOT NULL, field_ownership TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(logical_expansion_id, project_id) REFERENCES layer3_expansion_heads(id, project_id) ON DELETE CASCADE,
                    UNIQUE(logical_expansion_id, revision_number),
                    UNIQUE(logical_expansion_id, id),
                    CHECK(revision_number >= 1)
                );

                CREATE TABLE IF NOT EXISTS layer3_expansion_revision_states (
                    revision_id TEXT PRIMARY KEY, logical_expansion_id TEXT NOT NULL,
                    workflow_state TEXT NOT NULL, review_state TEXT NOT NULL,
                    freshness_state TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(revision_id) REFERENCES layer3_expansion_revisions(id) ON DELETE CASCADE,
                    FOREIGN KEY(logical_expansion_id) REFERENCES layer3_expansion_heads(id) ON DELETE CASCADE,
                    FOREIGN KEY(logical_expansion_id, revision_id) REFERENCES layer3_expansion_revisions(logical_expansion_id, id) ON DELETE CASCADE,
                    CHECK(workflow_state IN ('candidate', 'active', 'superseded', 'rejected', 'applied_partial')),
                    CHECK(review_state IN ('draft', 'approved', 'rejected', 'needs_review')),
                    CHECK(freshness_state IN ('fresh', 'stale', 'unknown')),
                    CHECK(
                        (workflow_state <> 'candidate' OR review_state = 'needs_review')
                        AND (workflow_state <> 'rejected' OR review_state = 'rejected')
                        AND (workflow_state <> 'applied_partial' OR review_state = 'approved')
                    )
                );

                CREATE TABLE IF NOT EXISTS layer3_revision_actions (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, project_id TEXT NOT NULL,
                    logical_expansion_id TEXT NOT NULL, revision_id TEXT,
                    action_type TEXT NOT NULL, expected_active_revision_id TEXT,
                    previous_active_revision_id TEXT, new_active_revision_id TEXT,
                    selected_sections TEXT NOT NULL, before_snapshot TEXT NOT NULL, after_snapshot TEXT NOT NULL,
                    actor TEXT NOT NULL, origin TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY(logical_expansion_id, project_id) REFERENCES layer3_expansion_heads(id, project_id) ON DELETE CASCADE,
                    FOREIGN KEY(logical_expansion_id, revision_id) REFERENCES layer3_expansion_revisions(logical_expansion_id, id) ON DELETE CASCADE
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

                CREATE INDEX IF NOT EXISTS idx_platform_jobs_project_updated
                ON platform_jobs(project_id, updated_at);

                CREATE INDEX IF NOT EXISTS idx_platform_jobs_dedupe
                ON platform_jobs(project_id, dedupe_key, status);

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

                CREATE INDEX IF NOT EXISTS idx_layer2_feature_embeddings_project
                ON layer2_feature_embeddings(project_id, feature_id);

                CREATE INDEX IF NOT EXISTS idx_overlap_verdicts_project_layer
                ON overlap_verdicts(project_id, layer, job_id);

                CREATE INDEX IF NOT EXISTS idx_overlap_job_items_job
                ON overlap_job_items(job_id, status);

                CREATE INDEX IF NOT EXISTS idx_overlap_clusters_project_layer
                ON overlap_clusters(project_id, layer, job_id);

                CREATE INDEX IF NOT EXISTS idx_overlap_resolutions_pair
                ON overlap_verdict_resolutions(project_id, layer, target_id, neighbor_id);

                CREATE INDEX IF NOT EXISTS idx_overlap_resolutions_verdict
                ON overlap_verdict_resolutions(verdict_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_layer2_review_project
                ON layer2_review_actions(project_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_artifact_authority_lookup
                ON artifact_authority_actions(project_id, artifact_type, artifact_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_critic_findings_project
                ON critic_findings(project_id, artifact_type, artifact_id, status, created_at);

                CREATE INDEX IF NOT EXISTS idx_command_executions_target
                ON command_executions(project_id, target_type, target_id, created_at);

                CREATE TRIGGER IF NOT EXISTS cleanup_node_critic_records
                AFTER DELETE ON nodes BEGIN
                    DELETE FROM critic_findings WHERE artifact_type = 'layer1_pillar' AND artifact_id = OLD.id;
                    DELETE FROM artifact_authority_actions WHERE artifact_type = 'layer1_pillar' AND artifact_id = OLD.id;
                END;

                CREATE TRIGGER IF NOT EXISTS cleanup_layer2_critic_records
                AFTER DELETE ON layer2_features BEGIN
                    DELETE FROM critic_findings WHERE artifact_type = 'layer2_feature' AND artifact_id = OLD.id;
                    DELETE FROM artifact_authority_actions WHERE artifact_type = 'layer2_feature' AND artifact_id = OLD.id;
                END;

                CREATE TRIGGER IF NOT EXISTS cleanup_layer3_critic_records
                AFTER DELETE ON layer3_expansion_heads BEGIN
                    DELETE FROM critic_findings WHERE artifact_type = 'layer3_expansion' AND artifact_id = OLD.id;
                    DELETE FROM artifact_authority_actions WHERE artifact_type = 'layer3_expansion' AND artifact_id = OLD.id;
                END;

                CREATE INDEX IF NOT EXISTS idx_layer2_coverage_matrix_pillar
                ON layer2_coverage_matrix(project_id, pillar_id, status);

                CREATE INDEX IF NOT EXISTS idx_layer2_shared_concern_project
                ON layer2_shared_concern_clusters(project_id, concern_type, status);

                CREATE INDEX IF NOT EXISTS idx_layer2_feature_evidence_feature
                ON layer2_feature_evidence(project_id, feature_id, competitor_name);

                CREATE INDEX IF NOT EXISTS idx_assistant_conversations_project
                ON assistant_conversations(project_id, archived, updated_at);

                CREATE INDEX IF NOT EXISTS idx_assistant_messages_conversation
                ON assistant_messages(conversation_id, created_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_assistant_message_request_role
                ON assistant_messages(conversation_id, request_id, role)
                WHERE request_id IS NOT NULL;

                CREATE INDEX IF NOT EXISTS idx_assistant_documents_project_scope
                ON assistant_documents(project_id, layer_scope, source_type);

                CREATE INDEX IF NOT EXISTS idx_layer3_expansions_project_review
                ON layer3_feature_expansions(project_id, review_state, feature_name);

                CREATE INDEX IF NOT EXISTS idx_layer3_expansion_actions_expansion
                ON layer3_expansion_actions(expansion_id, action_type);

                CREATE INDEX IF NOT EXISTS idx_layer3_revisions_logical_number
                ON layer3_expansion_revisions(logical_expansion_id, revision_number);

                CREATE INDEX IF NOT EXISTS idx_layer3_revision_actions_logical
                ON layer3_revision_actions(logical_expansion_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_model_call_events_project_started
                ON model_call_events(project_id, started_at);

                CREATE INDEX IF NOT EXISTS idx_model_call_events_project_layer
                ON model_call_events(project_id, layer, workflow);
                """
            )
            brief_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(project_briefs)").fetchall()
            }
            if "problem" not in brief_columns:
                conn.execute("ALTER TABLE project_briefs ADD COLUMN problem TEXT NOT NULL DEFAULT ''")
            expansion_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(layer3_feature_expansions)").fetchall()
            }
            if "active_revision_id" not in expansion_columns:
                conn.execute("ALTER TABLE layer3_feature_expansions ADD COLUMN active_revision_id TEXT NOT NULL DEFAULT ''")
            if "revision_number" not in expansion_columns:
                conn.execute("ALTER TABLE layer3_feature_expansions ADD COLUMN revision_number INTEGER NOT NULL DEFAULT 0")
        try:
            self._execute(
                "ALTER TABLE project_model_settings ADD COLUMN prompt_catalog TEXT NOT NULL DEFAULT '{}'"
            )
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        for statement in (
            "ALTER TABLE projects ADD COLUMN updated_at TEXT",
            "ALTER TABLE projects ADD COLUMN last_opened_at TEXT",
            "ALTER TABLE projects ADD COLUMN archived_at TEXT",
            "ALTER TABLE projects ADD COLUMN lifecycle_state TEXT NOT NULL DEFAULT 'active'",
            "ALTER TABLE projects ADD COLUMN source_project_id TEXT",
        ):
            try:
                self._execute(statement)
            except Exception as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        self._execute("UPDATE projects SET updated_at = created_at WHERE updated_at IS NULL")
        self._execute("UPDATE projects SET lifecycle_state = 'active' WHERE lifecycle_state IS NULL OR lifecycle_state = ''")
        for statement in (
            "ALTER TABLE project_model_settings ADD COLUMN execution_intent TEXT NOT NULL DEFAULT 'local_first'",
            "ALTER TABLE project_model_settings ADD COLUMN routing_policy TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE project_model_settings ADD COLUMN concurrency_policy TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE project_model_settings ADD COLUMN competitive_intelligence_enabled INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE project_model_settings ADD COLUMN discovery_settings TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE assistant_messages ADD COLUMN execution_intent_override TEXT",
            "ALTER TABLE assistant_runs ADD COLUMN execution_intent TEXT NOT NULL DEFAULT 'local_first'",
            "ALTER TABLE assistant_runs ADD COLUMN effective_parallelism INTEGER NOT NULL DEFAULT 1",
        ):
            try:
                self._execute(statement)
            except Exception as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        for statement in (
            "ALTER TABLE layer2_features ADD COLUMN granularity_class TEXT NOT NULL DEFAULT 'feature'",
            "ALTER TABLE layer2_negative_cache ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE layer2_negative_cache ADD COLUMN embedding TEXT",
            "ALTER TABLE layer2_feature_evidence ADD COLUMN rationale TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE layer2_feature_evidence ADD COLUMN research_job_id TEXT",
            "ALTER TABLE brief_conversations ADD COLUMN request_id TEXT",
        ):
            try:
                self._execute(statement)
            except Exception as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS layer3_feature_expansions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, feature_id TEXT NOT NULL,
                parent_pillar_id TEXT NOT NULL, parent_pillar_title TEXT NOT NULL,
                feature_name TEXT NOT NULL, feature_description TEXT NOT NULL DEFAULT '',
                feature_intent TEXT NOT NULL, expansion_groups TEXT NOT NULL,
                overlap_review TEXT NOT NULL, open_questions TEXT NOT NULL,
                review_state TEXT NOT NULL, provenance TEXT NOT NULL,
                active_revision_id TEXT NOT NULL DEFAULT '', revision_number INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                UNIQUE(project_id, feature_id)
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS layer3_expansion_actions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, expansion_id TEXT NOT NULL,
                action_type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id),
                FOREIGN KEY(expansion_id) REFERENCES layer3_feature_expansions(id)
            )
            """
        )
        self._execute(
            """
            CREATE INDEX IF NOT EXISTS idx_layer3_expansions_project_review
            ON layer3_feature_expansions(project_id, review_state, feature_name)
            """
        )
        self._execute(
            """
            CREATE INDEX IF NOT EXISTS idx_layer3_expansion_actions_expansion
            ON layer3_expansion_actions(expansion_id, action_type)
            """
        )
        self._execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_brief_conversations_request_role
            ON brief_conversations(project_id, request_id, role)
            WHERE request_id IS NOT NULL
            """
        )
