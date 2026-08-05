import { useState } from "react";
import { ModalFrame } from "./ProjectShell";
import { applyRuntimePreset, providerFormErrors, readinessTone, runtimePresets } from "./setupRuntime";

const DEFAULT_LLM_PROFILE_ID = "default-chat";
const DEFAULT_EMBEDDING_PROFILE_ID = "default-embedding";

const EXECUTION_INTENT_OPTIONS = [
  { value: "local_first", label: "Local-first", description: "Prefer managed local models and keep assistant orchestration conservative around local concurrency." },
  { value: "api_first", label: "API-first", description: "Prefer remote API profiles so assistant flows can use faster parallel orchestration." },
  { value: "blended", label: "Blended", description: "Keep generation and research local by default while routing assistant work to API profiles." },
];
const SETTINGS_SECTIONS = [
  { id: "compute", label: "Compute Mode" },
  { id: "profiles", label: "Model Profiles" },
  { id: "assignments", label: "Task Assignments" },
  { id: "discovery", label: "Discovery Runtime" },
  { id: "connection", label: "Connection" },
];
const ROUTING_DOMAINS = [
  { key: "layer0", label: "Layer 0" },
  { key: "generation", label: "Generation" },
  { key: "research", label: "Research" },
  { key: "review", label: "Review" },
  { key: "assistant", label: "Assistant" },
];
const ASSIGNMENT_GROUPS = [
  { title: "Layer 0", routingKey: "layer0", fields: ["layer0_plan", "layer0_extraction", "layer0_research"] },
  { title: "Product Discovery", routingKey: "generation", fields: ["product_discovery_generation", "cross_domain_exploration"] },
  { title: "Discovery Review", routingKey: "review", fields: ["discovery_practicality_review"] },
  { title: "Competitor Discovery", routingKey: "research", fields: ["competitor_evidence_extraction", "competitor_pillar_inference", "competitor_strategic_comparison"] },
  { title: "Generation", routingKey: "generation", fields: ["layer1_generation", "layer2_generation"] },
  { title: "Research & Embeddings", routingKey: "research", fields: ["layer1_research", "layer2_research", "layer1_similarity_embeddings", "layer2_similarity_embeddings", "research_embeddings"] },
  { title: "Review Critics", routingKey: "review", fields: ["layer1_overlap_critic", "layer2_overlap_critic"] },
  { title: "Assistant", routingKey: "assistant", fields: ["assistant_orchestration", "assistant_synthesis", "assistant_compaction", "assistant_specialists", "assistant_embeddings"] },
];

const LLM_ASSIGNMENT_LABELS = {
  layer0_plan: "Layer 0 Plan Chat",
  layer0_extraction: "Layer 0 Brief Extraction",
  product_discovery_generation: "Product Discovery Generation",
  cross_domain_exploration: "Cross-domain Exploration",
  discovery_practicality_review: "Discovery Practicality Review",
  competitor_evidence_extraction: "Competitor Evidence Extraction",
  competitor_pillar_inference: "Competitor Pillar Inference",
  competitor_strategic_comparison: "Competitor Strategic Comparison",
  layer1_generation: "Layer 1 Generation",
  layer2_generation: "Layer 2 Generation",
  layer1_overlap_critic: "Layer 1 Overlap Critic",
  layer2_overlap_critic: "Layer 2 Overlap Critic",
  layer0_research: "Layer 0 Research Discovery",
  layer1_research: "Layer 1 Research Discovery",
  layer2_research: "Layer 2 Feature Research",
  assistant_orchestration: "Assistant Orchestration",
  assistant_synthesis: "Assistant Synthesis",
  assistant_compaction: "Assistant Compaction",
  assistant_specialists: "Assistant Specialists",
};
const EMBEDDING_ASSIGNMENT_LABELS = {
  layer1_similarity_embeddings: "Layer 1 Similarity",
  layer2_similarity_embeddings: "Layer 2 Similarity",
  research_embeddings: "Research Embeddings",
  assistant_embeddings: "Assistant Retrieval",
};
const ASSIGNMENT_HELP = {
  layer0_plan: "Use this model for the live Layer 0 intake conversation and brief shaping.",
  layer0_extraction: "Use this model to turn Plan mode messages into structured brief fields.",
  product_discovery_generation: "Generates the structured Product Discovery candidate from an exact published brief revision.",
  cross_domain_exploration: "Explores bounded cross-domain opportunities without making them authoritative.",
  discovery_practicality_review: "Reviews discovery items for usefulness, superficiality, and unsupported claims without deleting them.",
  competitor_evidence_extraction: "Extracts structured claims only from retained competitor source evidence.",
  competitor_pillar_inference: "Infers competitor product pillars with explicit evidence links and confidence.",
  competitor_strategic_comparison: "Builds bounded territories, gaps, and derived lenses from approved competitive evidence.",
  layer1_generation: "Use one or more models to brainstorm and broaden the Layer 1 pillar set.",
  layer2_generation: "Use this model to expand selected pillars into Layer 2 subfeatures.",
  layer1_overlap_critic: "Reviews existing Layer 1 pillars for overlap after generation or manual edits.",
  layer2_overlap_critic: "Reviews the full Layer 2 feature graph for deeper overlap and fake novelty.",
  layer0_research: "Use this model to discover and summarize competitor evidence for Layer 0.",
  layer1_research: "Use this model to score how each Layer 1 pillar shows up across competitors.",
  layer2_research: "Use this model to classify competitor evidence across Layer 2 feature batches.",
  assistant_orchestration: "Plans bounded retrieval and specialist work for each assistant turn.",
  assistant_synthesis: "Writes the final grounded response and inert action previews.",
  assistant_compaction: "Maintains durable summaries when conversations exceed context budgets.",
  assistant_specialists: "Runs bounded Deep-mode and automatically triggered specialist reviews.",
  layer1_similarity_embeddings: "Use this embedding model to measure overlap between Layer 1 pillars.",
  layer2_similarity_embeddings: "Use this embedding model to shortlist neighboring Layer 2 features for overlap review.",
  research_embeddings: "Use this embedding model to index research pages and compare evidence chunks.",
  assistant_embeddings: "Indexes project entities for semantic assistant retrieval.",
};

function defaultRoutingPolicy(intent) {
  if (intent === "api_first") {
    return { layer0: "api", generation: "api", research: "api", assistant: "api" };
  }
  if (intent === "blended") {
    return { layer0: "local", generation: "local", research: "local", review: "local", assistant: "api" };
  }
  return { layer0: "local", generation: "local", research: "local", review: "local", assistant: "local" };
}

function providerLabel(value) {
  return value === "api" ? "Cloud/API" : "Local";
}

function profileSummary(profile, type) {
  if (type === "embedding") return profile.model_name || "No embedding model set";
  const parts = [profile.model_name, profile.base_url || profile.local_path].filter(Boolean);
  return parts.length ? parts.join(" / ") : "No model connection set";
}

function arraysEqual(left, right) {
  return JSON.stringify(left || []) === JSON.stringify(right || []);
}

function routingMatchesIntent(settings) {
  const intent = settings.execution_intent || "local_first";
  const expected = defaultRoutingPolicy(intent);
  const current = settings.routing_policy || expected;
  return ROUTING_DOMAINS.every((domain) => (current[domain.key] || "local") === expected[domain.key]);
}

function syncRuntimeFromDefaultProfiles(settings) {
  const defaultLlm = (settings.llm_profiles || []).find((profile) => profile.id === DEFAULT_LLM_PROFILE_ID);
  const defaultEmbedding = (settings.embedding_profiles || []).find((profile) => profile.id === DEFAULT_EMBEDDING_PROFILE_ID);
  return {
    ...settings,
    llama_base_url: defaultLlm?.base_url ?? settings.llama_base_url ?? "",
    llm_model_name: defaultLlm?.model_name ?? settings.llm_model_name ?? "",
    preferred_model_path: defaultLlm?.local_path ?? settings.preferred_model_path ?? "",
    context_window: defaultLlm?.context_window ?? settings.context_window ?? 32768,
    max_output_tokens: defaultLlm?.max_output_tokens ?? settings.max_output_tokens ?? 1800,
    embeddings_model_name: defaultEmbedding?.model_name ?? settings.embeddings_model_name ?? "",
  };
}

function updateDefaultProfilesFromRuntime(settings) {
  const withUpdatedProfiles = {
    ...settings,
    llm_profiles: (settings.llm_profiles || []).map((profile) => (
      profile.id === DEFAULT_LLM_PROFILE_ID
        ? {
            ...profile,
            base_url: settings.llama_base_url || "",
            model_name: settings.llm_model_name || settings.model_name || "",
            local_path: settings.preferred_model_path || "",
            context_window: settings.context_window || 32768,
            max_output_tokens: settings.max_output_tokens || 1800,
          }
        : profile
    )),
    embedding_profiles: (settings.embedding_profiles || []).map((profile) => (
      profile.id === DEFAULT_EMBEDDING_PROFILE_ID ? { ...profile, model_name: settings.embeddings_model_name || "" } : profile
    )),
  };
  return syncRuntimeFromDefaultProfiles(withUpdatedProfiles);
}

function SettingsOverview({ settings, config }) {
  const llmCount = settings?.llm_profiles?.length || 0;
  const embeddingCount = settings?.embedding_profiles?.length || 0;
  const assignmentCount = Object.keys(settings?.assignments || {}).length;
  const readiness = settings?.provider_readiness?.message || config?.provider_readiness?.message || "Runtime defaults are available for local or API-backed startup.";

  return (
    <section className="panel settings-overview">
      <div>
        <span className="guide-eyebrow">Global defaults</span>
        <h3>Defaults for new projects.</h3>
        <p className="muted">Set compute mode, model profiles, task routing, and the one global connection secret new projects inherit.</p>
      </div>
      <div className="settings-overview-facts" aria-label="Current app settings summary">
        <span><strong>{llmCount}</strong> LLM profile{llmCount === 1 ? "" : "s"}</span>
        <span><strong>{embeddingCount}</strong> embedding profile{embeddingCount === 1 ? "" : "s"}</span>
        <span><strong>{assignmentCount}</strong> assignments</span>
        <span>{readiness}</span>
      </div>
    </section>
  );
}

function SettingsNav({ activeSection, onSectionChange }) {
  return (
    <nav className="settings-subnav" aria-label="App settings sections">
      {SETTINGS_SECTIONS.map((section) => (
        <button
          key={section.id}
          type="button"
          className={activeSection === section.id ? "active" : ""}
          onClick={() => onSectionChange(section.id)}
        >
          {section.label}
        </button>
      ))}
    </nav>
  );
}

function ComputeModeSection({ settings, onChange }) {
  const executionIntent = settings.execution_intent || "local_first";
  const routingPolicy = settings.routing_policy || defaultRoutingPolicy(executionIntent);
  const isCustom = !routingMatchesIntent(settings);

  function updateExecutionIntent(value) {
    onChange({ ...settings, execution_intent: value, routing_policy: defaultRoutingPolicy(value) });
  }

  function resetToPreset() {
    onChange({ ...settings, routing_policy: defaultRoutingPolicy(executionIntent) });
  }

  return (
    <section className="panel settings-section">
      <div className="settings-section-head">
        <div>
          <h3>Compute Mode</h3>
          <p className="muted">Choose the default provider preference. Direct task routing changes below will mark this as Custom.</p>
        </div>
        {isCustom ? (
          <div className="settings-custom-state">
            <span>Custom routing</span>
            <button type="button" className="secondary-button" onClick={resetToPreset}>Reset to preset</button>
          </div>
        ) : null}
      </div>
      <div className="execution-option-grid">
        {EXECUTION_INTENT_OPTIONS.map((option) => (
          <label key={option.value} className={executionIntent === option.value && !isCustom ? "execution-option active" : "execution-option"}>
            <input
              type="radio"
              name="app-execution-intent"
              checked={executionIntent === option.value && !isCustom}
              onChange={() => updateExecutionIntent(option.value)}
            />
            <strong>{option.label}</strong>
            <span>{option.description}</span>
          </label>
        ))}
      </div>
      <div className="execution-summary-grid" aria-label="Current effective routing">
        {ROUTING_DOMAINS.map((domain) => (
          <div key={domain.key} className="execution-summary-item">
            <span>{domain.label}</span>
            <strong>{providerLabel(routingPolicy[domain.key] || "local")}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function ModelProfilesSection({ settings, config, onChange }) {
  const llmProfiles = settings.llm_profiles || [];
  const embeddingProfiles = settings.embedding_profiles || [];

  function updateLlmProfile(index, field, value) {
    const nextProfiles = llmProfiles.map((profile, profileIndex) => (
      profileIndex === index ? { ...profile, [field]: value } : profile
    ));
    onChange(syncRuntimeFromDefaultProfiles({ ...settings, llm_profiles: nextProfiles }));
  }

  function updateEmbeddingProfile(index, field, value) {
    const nextProfiles = embeddingProfiles.map((profile, profileIndex) => (
      profileIndex === index ? { ...profile, [field]: value } : profile
    ));
    onChange(syncRuntimeFromDefaultProfiles({ ...settings, embedding_profiles: nextProfiles }));
  }

  function addLlmProfile() {
    onChange({
      ...settings,
      llm_profiles: [
        ...llmProfiles,
        { id: `llm-${Date.now()}`, label: "New LLM", base_url: "", model_name: "", local_path: "", runtime_kind: "auto", context_window: 32768, supports_reasoning: true, supports_parallel: false, max_parallel_requests: 1, max_specialists: 2, max_output_tokens: 1800, input_cost_per_million: 0, output_cost_per_million: 0 },
      ],
    });
  }

  function addEmbeddingProfile() {
    onChange({
      ...settings,
      embedding_profiles: [
        ...embeddingProfiles,
        { id: `embed-${Date.now()}`, label: "New Embeddings", model_name: "" },
      ],
    });
  }

  return (
    <section className="panel settings-section">
      <div className="settings-section-head">
        <div>
          <h3>Model Profiles</h3>
          <p className="muted">Edit model connection fields here. The default profile mirrors the runtime fields required by the existing settings API.</p>
        </div>
        <div className="button-row compact">
          <button type="button" className="secondary-button" onClick={addLlmProfile}>Add LLM</button>
          <button type="button" className="secondary-button" onClick={addEmbeddingProfile}>Add Embeddings</button>
        </div>
      </div>
      <div className="profile-row-list">
        {llmProfiles.map((profile, index) => (
          <details key={profile.id || index} className="settings-profile-row">
            <summary>
              <span className="status-pill">LLM</span>
              <strong>{profile.label || `LLM ${index + 1}`}</strong>
              <span className="muted">{profile.id}</span>
              <span>{profileSummary(profile, "llm")}</span>
            </summary>
            <div className="brief-grid settings-profile-fields">
              <label>Profile ID<input value={profile.id || ""} onChange={(event) => updateLlmProfile(index, "id", event.target.value)} /></label>
              <label>Label<input value={profile.label || ""} onChange={(event) => updateLlmProfile(index, "label", event.target.value)} /></label>
              <label>API Base URL<input value={profile.base_url || ""} onChange={(event) => updateLlmProfile(index, "base_url", event.target.value)} placeholder="http://127.0.0.1:8080" /></label>
              <label>Model Name<input value={profile.model_name || ""} onChange={(event) => updateLlmProfile(index, "model_name", event.target.value)} placeholder="qwen-27b-q3-no-thinking" /></label>
              <label>Local GGUF Path<input value={profile.local_path || ""} onChange={(event) => updateLlmProfile(index, "local_path", event.target.value)} placeholder="C:\\models\\my-model.gguf" /></label>
              <label>Runtime<select value={profile.runtime_kind || "auto"} onChange={(event) => updateLlmProfile(index, "runtime_kind", event.target.value)}><option value="auto">Auto detect</option><option value="managed_local">Managed local</option><option value="remote_api">Remote API</option></select></label>
              <label>Context Window<input type="number" min="2048" value={profile.context_window || 32768} onChange={(event) => updateLlmProfile(index, "context_window", Number(event.target.value))} /></label>
              <label>Max Output Tokens<input type="number" min="256" max="16000" value={profile.max_output_tokens || 1800} onChange={(event) => updateLlmProfile(index, "max_output_tokens", Number(event.target.value))} /></label>
              <label>Input Cost / 1M Tokens<input type="number" min="0" step="0.000001" value={profile.input_cost_per_million || 0} onChange={(event) => updateLlmProfile(index, "input_cost_per_million", Number(event.target.value))} /></label>
              <label>Output Cost / 1M Tokens<input type="number" min="0" step="0.000001" value={profile.output_cost_per_million || 0} onChange={(event) => updateLlmProfile(index, "output_cost_per_million", Number(event.target.value))} /></label>
              <label>Max Specialists<input type="number" min="0" max="16" value={profile.max_specialists ?? 2} onChange={(event) => updateLlmProfile(index, "max_specialists", Number(event.target.value))} /></label>
              <label className="checkbox-item"><input type="checkbox" checked={profile.supports_reasoning ?? true} onChange={(event) => updateLlmProfile(index, "supports_reasoning", event.target.checked)} /> Supports thinking</label>
              <label className="checkbox-item"><input type="checkbox" checked={profile.supports_parallel || false} onChange={(event) => updateLlmProfile(index, "supports_parallel", event.target.checked)} /> Parallel requests</label>
              {profile.supports_parallel ? <label>Max Parallel Requests<input type="number" min="1" max="32" value={profile.max_parallel_requests || 1} onChange={(event) => updateLlmProfile(index, "max_parallel_requests", Number(event.target.value))} /></label> : null}
            </div>
            {profile.id !== DEFAULT_LLM_PROFILE_ID ? (
              <button type="button" className="secondary-button" onClick={() => onChange({ ...settings, llm_profiles: llmProfiles.filter((_, profileIndex) => profileIndex !== index) })}>Remove LLM profile</button>
            ) : null}
          </details>
        ))}
        {embeddingProfiles.map((profile, index) => (
          <details key={profile.id || index} className="settings-profile-row">
            <summary>
              <span className="status-pill">Embedding</span>
              <strong>{profile.label || `Embeddings ${index + 1}`}</strong>
              <span className="muted">{profile.id}</span>
              <span>{profileSummary(profile, "embedding")}</span>
            </summary>
            <div className="brief-grid settings-profile-fields">
              <label>Profile ID<input value={profile.id || ""} onChange={(event) => updateEmbeddingProfile(index, "id", event.target.value)} /></label>
              <label>Label<input value={profile.label || ""} onChange={(event) => updateEmbeddingProfile(index, "label", event.target.value)} /></label>
              <label>Model ID or Local Path<input value={profile.model_name || ""} onChange={(event) => updateEmbeddingProfile(index, "model_name", event.target.value)} placeholder="sentence-transformers/all-MiniLM-L6-v2" /></label>
            </div>
            <div className="preset-grid">
              {(config.embedding_model_presets || []).map((preset) => (
                <button key={`${profile.id}-${preset}`} type="button" className="preset-chip" onClick={() => updateEmbeddingProfile(index, "model_name", preset)}>{preset}</button>
              ))}
            </div>
            {profile.id !== DEFAULT_EMBEDDING_PROFILE_ID ? (
              <button type="button" className="secondary-button" onClick={() => onChange({ ...settings, embedding_profiles: embeddingProfiles.filter((_, profileIndex) => profileIndex !== index) })}>Remove embedding profile</button>
            ) : null}
          </details>
        ))}
      </div>
    </section>
  );
}

function AssignmentControl({ assignmentKey, assignments, llmProfiles, embeddingProfiles, onAssignmentChange }) {
  const isEmbeddingField = assignmentKey in EMBEDDING_ASSIGNMENT_LABELS;
  const isMultiModel = assignmentKey === "layer1_generation";
  const options = isEmbeddingField ? embeddingProfiles : llmProfiles;
  const current = assignments[assignmentKey];

  if (isMultiModel) {
    const selected = Array.isArray(current) ? current : [];
    return (
      <div className="assignment-chip-picker">
        {options.map((profile) => {
          const checked = selected.includes(profile.id);
          return (
            <label key={`${assignmentKey}-${profile.id}`} className={checked ? "assignment-chip active" : "assignment-chip"}>
              <input
                type="checkbox"
                checked={checked}
                onChange={(event) => {
                  if (event.target.checked) {
                    onAssignmentChange(assignmentKey, [...selected, profile.id]);
                    return;
                  }
                  onAssignmentChange(assignmentKey, selected.filter((item) => item !== profile.id));
                }}
              />
              {profile.label}
            </label>
          );
        })}
      </div>
    );
  }

  return (
    <select value={current || ""} onChange={(event) => onAssignmentChange(assignmentKey, event.target.value)}>
      {options.map((profile) => (
        <option key={profile.id} value={profile.id}>{profile.label}</option>
      ))}
    </select>
  );
}

function TaskAssignmentsSection({ settings, onChange }) {
  const llmProfiles = settings.llm_profiles || [];
  const embeddingProfiles = settings.embedding_profiles || [];
  const assignments = settings.assignments || {};
  const routingPolicy = settings.routing_policy || defaultRoutingPolicy(settings.execution_intent || "local_first");
  const concurrencyPolicy = settings.concurrency_policy || { managed_local_parallelism: 1, remote_parallelism: 4 };

  function updateAssignment(field, value) {
    onChange({ ...settings, assignments: { ...assignments, [field]: value } });
  }

  function updateRoutingPolicy(field, value) {
    onChange({ ...settings, routing_policy: { ...routingPolicy, [field]: value } });
  }

  function updateConcurrency(field, value) {
    onChange({ ...settings, concurrency_policy: { ...concurrencyPolicy, [field]: value } });
  }

  return (
    <section className="panel settings-section">
      <div className="settings-section-head">
        <h3>Task Assignments</h3>
        <p className="muted">Route each task to a profile. Routing controls here are what make Compute Mode custom.</p>
      </div>
      <div className="settings-assignment-table-wrap">
        <table className="settings-assignment-table">
          <thead>
            <tr>
              <th scope="col">Task name</th>
              <th scope="col">Model / embedding assignment</th>
              <th scope="col">Mode</th>
            </tr>
          </thead>
          {ASSIGNMENT_GROUPS.map((group) => (
            <tbody key={group.title}>
              <tr className="assignment-stage-row">
                <th colSpan="3">
                  <div>
                    <strong>{group.title}</strong>
                    <label>
                      Routing
                      <select value={routingPolicy[group.routingKey] || "local"} onChange={(event) => updateRoutingPolicy(group.routingKey, event.target.value)}>
                        <option value="local">Prefer local</option>
                        <option value="api">Prefer API</option>
                      </select>
                    </label>
                    {["assistant", "review"].includes(group.routingKey) ? (
                      <span className="assignment-parallelism">
                        <label>Local parallelism<input type="number" min="1" max="4" value={concurrencyPolicy.managed_local_parallelism ?? 1} onChange={(event) => updateConcurrency("managed_local_parallelism", Number(event.target.value))} /></label>
                        <label>API parallelism<input type="number" min="1" max="16" value={concurrencyPolicy.remote_parallelism ?? 4} onChange={(event) => updateConcurrency("remote_parallelism", Number(event.target.value))} /></label>
                      </span>
                    ) : null}
                  </div>
                </th>
              </tr>
              {group.fields.map((key) => {
                const label = LLM_ASSIGNMENT_LABELS[key] || EMBEDDING_ASSIGNMENT_LABELS[key];
                const isMultiModel = key === "layer1_generation";
                return (
                  <tr key={key}>
                    <td>
                      <span className="assignment-task-name">
                        <strong>{label}</strong>
                        <span className="tooltip-chip" aria-label={ASSIGNMENT_HELP[key]} title={ASSIGNMENT_HELP[key]}>?</span>
                      </span>
                    </td>
                    <td>
                      <AssignmentControl
                        assignmentKey={key}
                        assignments={assignments}
                        llmProfiles={llmProfiles}
                        embeddingProfiles={embeddingProfiles}
                        onAssignmentChange={updateAssignment}
                      />
                    </td>
                    <td>{isMultiModel ? <span className="status-pill">multi-model</span> : <span className="muted">single</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
}

function ConnectionSection({ settings, config, onChange }) {
  const runtimeReadiness = settings.provider_readiness || config?.provider_readiness || {};
  const runtimePresetOptions = runtimePresets(config?.runtime_presets);
  const runtimeFieldErrors = providerFormErrors(syncRuntimeFromDefaultProfiles(settings));

  function updateRootField(field, value) {
    onChange({ ...settings, [field]: value });
  }

  function applyPreset(preset) {
    onChange(updateDefaultProfilesFromRuntime(applyRuntimePreset(settings, preset)));
  }

  return (
    <section className="panel settings-section">
      <div className="settings-section-head">
        <h3>Connection</h3>
        <p className="muted">Only global connection state lives here. Profile-specific URL, model, GGUF, context, and token limits are edited in Model Profiles.</p>
      </div>
      <div className="settings-block compact-block">
        <h4>Runtime presets</h4>
        <div className="button-row compact" aria-label="Runtime presets">
          {runtimePresetOptions.map((preset) => (
            <button key={preset.id || preset.label} type="button" className="secondary-button" onClick={() => applyPreset(preset)}>{preset.label}</button>
          ))}
        </div>
      </div>
      <div className="brief-grid">
        <label>
          Bearer Token
          <input
            type="password"
            autoComplete="new-password"
            value={settings.bearer_token || ""}
            placeholder={settings.has_bearer_token ? "Token saved on server" : "Optional"}
            onChange={(event) => updateRootField("bearer_token", event.target.value)}
          />
        </label>
        <label className="checkbox-item">
          <input
            type="checkbox"
            checked={settings.clear_bearer_token || false}
            onChange={(event) => onChange({ ...settings, clear_bearer_token: event.target.checked, bearer_token: event.target.checked ? "" : settings.bearer_token || "" })}
          />
          Remove saved bearer token
        </label>
      </div>
      {runtimeFieldErrors.llama_base_url ? <div className="error-banner">{runtimeFieldErrors.llama_base_url}</div> : null}
      {runtimeFieldErrors.model_name ? <div className="error-banner">{runtimeFieldErrors.model_name}</div> : null}
      {runtimeFieldErrors.embeddings_model_name ? <div className="error-banner">{runtimeFieldErrors.embeddings_model_name}</div> : null}
      {runtimeFieldErrors.context_window ? <div className="error-banner">{runtimeFieldErrors.context_window}</div> : null}
      {runtimeFieldErrors.max_output_tokens ? <div className="error-banner">{runtimeFieldErrors.max_output_tokens}</div> : null}
      {runtimeReadiness?.message ? <div className={`status-card ${readinessTone(runtimeReadiness)}`}>{runtimeReadiness.message}</div> : null}
    </section>
  );
}

function DiscoveryRuntimeSection({ settings, onChange }) {
  const discovery = settings.discovery_settings || {};
  const update = (field, value) => onChange({
    ...settings,
    discovery_settings: { ...discovery, [field]: value },
  });
  return (
    <section className="panel settings-section">
      <div className="settings-section-head">
        <h3>Product Discovery runtime</h3>
        <p className="muted">Tune independent generation, review, and competitor-research passes. These settings never start a workflow automatically.</p>
      </div>
      <div className="brief-grid settings-profile-fields">
        <label>Discovery temperature<input type="number" min="0" max="2" step="0.05" value={discovery.generation_temperature ?? 0.7} onChange={(event) => update("generation_temperature", Number(event.target.value))} /></label>
        <label>Cross-domain temperature<input type="number" min="0" max="2" step="0.05" value={discovery.cross_domain_temperature ?? 0.9} onChange={(event) => update("cross_domain_temperature", Number(event.target.value))} /></label>
        <label>Practicality review temperature<input type="number" min="0" max="2" step="0.05" value={discovery.practicality_review_temperature ?? 0.2} onChange={(event) => update("practicality_review_temperature", Number(event.target.value))} /></label>
        <label>Evidence extraction temperature<input type="number" min="0" max="2" step="0.05" value={discovery.competitor_evidence_temperature ?? 0.2} onChange={(event) => update("competitor_evidence_temperature", Number(event.target.value))} /></label>
        <label>Competitor inference temperature<input type="number" min="0" max="2" step="0.05" value={discovery.competitor_pillar_temperature ?? 0.5} onChange={(event) => update("competitor_pillar_temperature", Number(event.target.value))} /></label>
        <label>Strategic comparison temperature<input type="number" min="0" max="2" step="0.05" value={discovery.competitor_comparison_temperature ?? 0.5} onChange={(event) => update("competitor_comparison_temperature", Number(event.target.value))} /></label>
        <label>Generation output tokens<input type="number" min="256" max="12000" value={discovery.generation_max_output_tokens ?? 1800} onChange={(event) => update("generation_max_output_tokens", Number(event.target.value))} /></label>
        <label>Review output tokens<input type="number" min="256" max="6000" value={discovery.practicality_review_max_output_tokens ?? 1800} onChange={(event) => update("practicality_review_max_output_tokens", Number(event.target.value))} /></label>
        <label>Optional deterministic seed<input type="number" value={discovery.seed ?? ""} placeholder="Provider default" onChange={(event) => update("seed", event.target.value === "" ? null : Number(event.target.value))} /></label>
      </div>
    </section>
  );
}

function StickySaveBar({ saveState, saveLabel, onSave }) {
  return (
    <div className="settings-sticky-save" role="region" aria-label="Settings save controls">
      <span>{saveState === "saved" ? "Saved" : saveState === "error" ? "Save failed" : "Unsaved changes stay local until saved."}</span>
      <button type="button" onClick={onSave} disabled={saveState === "saving"}>
        {saveState === "saving" ? "Saving..." : saveLabel}
      </button>
    </div>
  );
}

function ModelSettingsEditor({
  settings,
  config,
  saveState,
  onChange,
  onSave,
  saveLabel,
  showCompetitiveControl = false,
  appMode = false,
}) {
  const [activeSection, setActiveSection] = useState("compute");

  if (!settings) {
    return (
      <div className="panel">
        <p className="muted">Settings are loading.</p>
      </div>
    );
  }

  function saveSettings() {
    onSave(syncRuntimeFromDefaultProfiles(settings));
  }

  return (
    <div className="settings-editor">
      {showCompetitiveControl ? (
        <div className="panel">
          <h3>Competitive intelligence</h3>
          <label className="checkbox-item">
            <input
              type="checkbox"
              checked={settings.competitive_intelligence_enabled ?? true}
              onChange={(event) => onChange({ ...settings, competitive_intelligence_enabled: event.target.checked })}
            />
            Enable competitive intelligence for this project
          </label>
          <p className="muted">When disabled, Strata will not queue or run competitor research from Layer 0, Layer 1, Layer 2, or assistant actions.</p>
        </div>
      ) : null}

      {appMode ? <SettingsNav activeSection={activeSection} onSectionChange={setActiveSection} /> : null}

      {(!appMode || activeSection === "compute") ? <ComputeModeSection settings={settings} onChange={onChange} /> : null}
      {(!appMode || activeSection === "profiles") ? <ModelProfilesSection settings={settings} config={config} onChange={onChange} /> : null}
      {(!appMode || activeSection === "assignments") ? <TaskAssignmentsSection settings={settings} onChange={onChange} /> : null}
      {(!appMode || activeSection === "discovery") ? <DiscoveryRuntimeSection settings={settings} onChange={onChange} /> : null}
      {appMode && activeSection === "connection" ? <ConnectionSection settings={settings} config={config} onChange={onChange} /> : null}

      <StickySaveBar saveState={saveState} saveLabel={saveLabel} onSave={saveSettings} />
    </div>
  );
}

export function AppSettingsModal({ settings, config, saveState, onChange, onSave, onClose }) {
  return (
    <ModalFrame
      title="App Settings"
      subtitle="Manage reusable app defaults, model profiles, embeddings, and assignment routing for new projects."
      onClose={onClose}
      className="settings-modal"
    >
      <div className="tab-content settings-modal-stack">
        <SettingsOverview settings={settings} config={config} />
        <ModelSettingsEditor
          settings={settings}
          config={config}
          saveState={saveState}
          onChange={onChange}
          onSave={onSave}
          saveLabel="Save App Settings"
          appMode
        />
      </div>
    </ModalFrame>
  );
}

export function ProjectSettingsTab({ settings, config, saveState, onChange, onSave }) {
  if (!settings) {
    return (
      <section className="tab-content">
        <div className="panel">
          <p className="muted">Project settings are loading.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="tab-content">
      <ModelSettingsEditor
        settings={settings}
        config={config}
        saveState={saveState}
        onChange={onChange}
        onSave={onSave}
        saveLabel="Save Project Overrides"
        showCompetitiveControl
      />
    </section>
  );
}
