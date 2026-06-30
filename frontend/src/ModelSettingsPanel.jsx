import { ModalFrame } from "./ProjectShell";
import { applyRuntimePreset, providerFormErrors, readinessTone, runtimePresets } from "./setupRuntime";

const EXECUTION_INTENT_OPTIONS = [
  { value: "local_first", label: "Local-first", description: "Prefer managed local models and keep assistant orchestration conservative around local concurrency." },
  { value: "api_first", label: "API-first", description: "Prefer remote API profiles so assistant flows can use faster parallel orchestration." },
  { value: "blended", label: "Blended", description: "Keep generation and research local by default while routing assistant work to API profiles." },
];
const ROUTING_DOMAINS = [
  { key: "layer0", label: "Layer 0" },
  { key: "generation", label: "Generation" },
  { key: "research", label: "Research" },
  { key: "assistant", label: "Assistant" },
];

const LLM_ASSIGNMENT_LABELS = {
  layer0_plan: "Layer 0 Plan Chat",
  layer0_extraction: "Layer 0 Brief Extraction",
  layer1_generation: "Layer 1 Generation",
  layer2_generation: "Layer 2 Generation",
  layer3_generation: "Layer 3 Capability Design",
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
  research_embeddings: "Research Embeddings",
  assistant_embeddings: "Assistant Retrieval",
};
const ASSIGNMENT_HELP = {
  layer0_plan: "Use this model for the live Layer 0 intake conversation and brief shaping.",
  layer0_extraction: "Use this model to turn Plan mode messages into structured brief fields.",
  layer1_generation: "Use one or more models to brainstorm and broaden the Layer 1 pillar set.",
  layer2_generation: "Use this model to expand selected pillars into Layer 2 subfeatures.",
  layer3_generation: "Use this model to draft and pressure-test product-level Capability Design Cards.",
  layer0_research: "Use this model to discover and summarize competitor evidence for Layer 0.",
  layer1_research: "Use this model to score how each Layer 1 pillar shows up across competitors.",
  layer2_research: "Use this model to classify competitor evidence across Layer 2 feature batches.",
  assistant_orchestration: "Plans bounded retrieval and specialist work for each assistant turn.",
  assistant_synthesis: "Writes the final grounded response and inert action previews.",
  assistant_compaction: "Maintains durable summaries when conversations exceed context budgets.",
  assistant_specialists: "Runs bounded Deep-mode and automatically triggered specialist reviews.",
  layer1_similarity_embeddings: "Use this embedding model to measure overlap between Layer 1 pillars.",
  research_embeddings: "Use this embedding model to index research pages and compare evidence chunks.",
  assistant_embeddings: "Indexes project entities for semantic assistant retrieval.",
};

function defaultRoutingPolicy(intent) {
  if (intent === "api_first") {
    return { layer0: "api", generation: "api", research: "api", assistant: "api" };
  }
  if (intent === "blended") {
    return { layer0: "local", generation: "local", research: "local", assistant: "api" };
  }
  return { layer0: "local", generation: "local", research: "local", assistant: "local" };
}

function providerLabel(value) {
  return value === "api" ? "Cloud/API" : "Local";
}

// Wraps one model assignment control with consistent help text.
function AssignmentField({ label, help, children }) {
  return (
    <div className="assignment-field" title={help}>
      <div className="assignment-label-row">
        <strong>{label}</strong>
        <span className="tooltip-chip" aria-label={help} title={help}>?</span>
      </div>
      <p className="field-help">{help}</p>
      {children}
    </div>
  );
}

function ModelSettingsEditor({
  settings,
  config,
  saveState,
  onChange,
  onSave,
  title,
  description,
  saveLabel,
  showRuntimeFields = false,
  showCompetitiveControl = false,
  savePlacement = "header",
}) {
  // Shared editor for app defaults and project-level model overrides.
  if (!settings) {
    return (
      <div className="panel">
        <p className="muted">Settings are loading.</p>
      </div>
    );
  }

  const llmProfiles = settings.llm_profiles || [];
  const embeddingProfiles = settings.embedding_profiles || [];
  const assignments = settings.assignments || {};
  const executionIntent = settings.execution_intent || "local_first";
  const routingPolicy = settings.routing_policy || defaultRoutingPolicy(executionIntent);
  const concurrencyPolicy = settings.concurrency_policy || { managed_local_parallelism: 1, remote_parallelism: 4 };
  const selectedIntent = EXECUTION_INTENT_OPTIONS.find((option) => option.value === executionIntent) || EXECUTION_INTENT_OPTIONS[0];
  const runtimeFieldErrors = showRuntimeFields ? providerFormErrors({
    llama_base_url: settings.llama_base_url,
    llm_model_name: settings.llm_model_name,
    embeddings_model_name: settings.embeddings_model_name,
    context_window: settings.context_window,
    max_output_tokens: settings.max_output_tokens,
  }) : {};
  const runtimeReadiness = settings.provider_readiness || config?.provider_readiness || {};
  const runtimePresetOptions = runtimePresets(config?.runtime_presets);

  // Updates scalar runtime defaults, such as active base URL/model name.
  function updateRootField(field, value) {
    onChange({ ...settings, [field]: value });
  }

  // Mutates one LLM profile without changing other profile rows.
  function updateLlmProfile(index, field, value) {
    const next = llmProfiles.map((profile, profileIndex) => (
      profileIndex === index ? { ...profile, [field]: value } : profile
    ));
    onChange({ ...settings, llm_profiles: next });
  }

  // Mutates one embedding profile without changing other profile rows.
  function updateEmbeddingProfile(index, field, value) {
    const next = embeddingProfiles.map((profile, profileIndex) => (
      profileIndex === index ? { ...profile, [field]: value } : profile
    ));
    onChange({ ...settings, embedding_profiles: next });
  }

  // Sets which profile each generation/research role should use.
  function updateAssignment(field, value) {
    onChange({ ...settings, assignments: { ...assignments, [field]: value } });
  }

  function updateExecutionIntent(value) {
    onChange({
      ...settings,
      execution_intent: value,
      routing_policy: defaultRoutingPolicy(value),
    });
  }

  function updateRoutingPolicy(field, value) {
    onChange({ ...settings, routing_policy: { ...routingPolicy, [field]: value } });
  }

  function updateConcurrency(field, value) {
    onChange({ ...settings, concurrency_policy: { ...concurrencyPolicy, [field]: value } });
  }

  // Appends a blank LLM profile row for user tuning.
  function addLlmProfile() {
    onChange({
      ...settings,
      llm_profiles: [
        ...llmProfiles,
        { id: `llm-${Date.now()}`, label: "New LLM", base_url: "", model_name: "", local_path: "", runtime_kind: "auto", context_window: 32768, supports_reasoning: true, supports_parallel: false, max_parallel_requests: 1, max_specialists: 2, max_output_tokens: 1800, input_cost_per_million: 0, output_cost_per_million: 0 },
      ],
    });
  }

  // Appends a blank embedding profile row for similarity/search tuning.
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
    <div className="settings-editor">
      <div className="panel">
        <div className="panel-header">
          <h3>{title}</h3>
          {savePlacement === "header" ? (
            <button type="button" onClick={onSave} disabled={saveState === "saving"}>
              {saveState === "saving" ? "Saving..." : saveLabel}
            </button>
          ) : null}
        </div>
        <p className="muted">{description}</p>
      </div>

      <div className="panel">
        <h3>Compute Mode</h3>
        <p className="muted">Pick how Strata should spend model work. Local protects cost and privacy; Cloud/API can support more parallel assistant work; Blended keeps generation local while using API flexibility for the assistant.</p>
        <div className="execution-option-grid">
          {EXECUTION_INTENT_OPTIONS.map((option) => (
            <label key={option.value} className={executionIntent === option.value ? "execution-option active" : "execution-option"}>
              <input
                type="radio"
                name={`${title}-execution-intent`}
                checked={executionIntent === option.value}
                onChange={() => updateExecutionIntent(option.value)}
              />
              <strong>{option.label}</strong>
              <span>{option.description}</span>
            </label>
          ))}
        </div>
        <div className="execution-summary-grid" aria-label={`${selectedIntent.label} routing summary`}>
          {ROUTING_DOMAINS.map((domain) => (
            <div key={domain.key} className="execution-summary-item">
              <span>{domain.label}</span>
              <strong>{providerLabel(routingPolicy[domain.key] || "local")}</strong>
            </div>
          ))}
        </div>
        <p className="field-help">Assistant specialist fanout is capped at {concurrencyPolicy.managed_local_parallelism ?? 1} local request and {concurrencyPolicy.remote_parallelism ?? 4} API requests. Advanced controls below can override this routing.</p>
      </div>

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

      <details className="panel advanced-settings">
        <summary>Advanced runtime and routing controls</summary>
        {showRuntimeFields ? (
          <div className="settings-block">
            <h3>Runtime Defaults</h3>
            <div className="button-row compact" aria-label="Runtime presets">
              {runtimePresetOptions.map((preset) => (
                <button key={preset.id || preset.label} type="button" className="secondary-button" onClick={() => onChange(applyRuntimePreset(settings, preset))}>{preset.label}</button>
              ))}
            </div>
            <div className="brief-grid">
              <label>
                Chat API Base URL
                <input
                  value={settings.llama_base_url || ""}
                  onChange={(event) => updateRootField("llama_base_url", event.target.value)}
                  placeholder="http://127.0.0.1:8080"
                />
              </label>
              <label>
                Default Chat Model Name
                <input
                  value={settings.llm_model_name || ""}
                  onChange={(event) => updateRootField("llm_model_name", event.target.value)}
                  placeholder="qwen-27b-q3-no-thinking"
                />
              </label>
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
              <label>
                Default Local GGUF Path
                <input
                  value={settings.preferred_model_path || ""}
                  onChange={(event) => updateRootField("preferred_model_path", event.target.value)}
                  placeholder="C:\\models\\my-model.gguf"
                />
              </label>
              <label>
                Default Embedding Model
                <input
                  value={settings.embeddings_model_name || ""}
                  onChange={(event) => updateRootField("embeddings_model_name", event.target.value)}
                  placeholder="sentence-transformers/all-MiniLM-L6-v2"
                />
              </label>
              <label>
                Context Window
                <input
                  type="number"
                  min="2048"
                  value={settings.context_window || 32768}
                  onChange={(event) => updateRootField("context_window", Number(event.target.value))}
                />
              </label>
              <label>
                Max Output Tokens
                <input
                  type="number"
                  min="256"
                  max="16000"
                  value={settings.max_output_tokens || 1800}
                  onChange={(event) => updateRootField("max_output_tokens", Number(event.target.value))}
                />
              </label>
            </div>
            <label className="checkbox-item">
              <input
                type="checkbox"
                checked={settings.clear_bearer_token || false}
                onChange={(event) => onChange({ ...settings, clear_bearer_token: event.target.checked, bearer_token: event.target.checked ? "" : settings.bearer_token || "" })}
              />
              Remove saved bearer token
            </label>
            {runtimeFieldErrors.llama_base_url ? <div className="error-banner">{runtimeFieldErrors.llama_base_url}</div> : null}
            {runtimeFieldErrors.model_name ? <div className="error-banner">{runtimeFieldErrors.model_name}</div> : null}
            {runtimeFieldErrors.embeddings_model_name ? <div className="error-banner">{runtimeFieldErrors.embeddings_model_name}</div> : null}
            {runtimeFieldErrors.context_window ? <div className="error-banner">{runtimeFieldErrors.context_window}</div> : null}
            {runtimeFieldErrors.max_output_tokens ? <div className="error-banner">{runtimeFieldErrors.max_output_tokens}</div> : null}
            {runtimeReadiness?.message ? <div className={`status-card ${readinessTone(runtimeReadiness)}`}>{runtimeReadiness.message}</div> : null}
            <div className="preset-grid">
              {(config.embedding_model_presets || []).map((preset) => (
                <button key={preset} type="button" className="preset-chip" onClick={() => updateRootField("embeddings_model_name", preset)}>
                  {preset}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <div className="settings-block">
          <h3>Routing Overrides</h3>
          <div className="brief-grid">
            {ROUTING_DOMAINS.map((domain) => (
              <label key={domain.key}>
                {domain.label} Routing
                <select value={routingPolicy[domain.key] || "local"} onChange={(event) => updateRoutingPolicy(domain.key, event.target.value)}>
                  <option value="local">Prefer local</option>
                  <option value="api">Prefer API</option>
                </select>
              </label>
            ))}
            <label>
              Assistant Local Parallelism
              <input
                type="number"
                min="1"
                max="4"
                value={concurrencyPolicy.managed_local_parallelism ?? 1}
                onChange={(event) => updateConcurrency("managed_local_parallelism", Number(event.target.value))}
              />
            </label>
            <label>
              Assistant API Parallelism
              <input
                type="number"
                min="1"
                max="16"
                value={concurrencyPolicy.remote_parallelism ?? 4}
                onChange={(event) => updateConcurrency("remote_parallelism", Number(event.target.value))}
              />
            </label>
          </div>
          <p className="field-help">These parallelism caps currently control assistant specialist fanout. Generation and research still use their own bounded execution paths.</p>
        </div>

        <div className="settings-block">
        <div className="panel-header">
          <h3>LLM Profiles</h3>
          <button type="button" onClick={addLlmProfile}>Add LLM</button>
        </div>
        {llmProfiles.map((profile, index) => (
          <div key={profile.id || index} className="settings-block">
            <div className="panel-header">
              <strong>{profile.label || `LLM ${index + 1}`}</strong>
              <button type="button" className="secondary-button" onClick={() => onChange({ ...settings, llm_profiles: llmProfiles.filter((_, profileIndex) => profileIndex !== index) })}>
                Remove
              </button>
            </div>
            <div className="brief-grid">
              <label>
                Profile ID
                <input value={profile.id || ""} onChange={(event) => updateLlmProfile(index, "id", event.target.value)} />
              </label>
              <label>
                Label
                <input value={profile.label || ""} onChange={(event) => updateLlmProfile(index, "label", event.target.value)} />
              </label>
              <label>
                API Base URL
                <input value={profile.base_url || ""} onChange={(event) => updateLlmProfile(index, "base_url", event.target.value)} placeholder="http://127.0.0.1:8080" />
              </label>
              <label>
                Model Name
                <input value={profile.model_name || ""} onChange={(event) => updateLlmProfile(index, "model_name", event.target.value)} placeholder="qwen-27b-q3-no-thinking" />
              </label>
              <label>
                Local GGUF Path
                <input value={profile.local_path || ""} onChange={(event) => updateLlmProfile(index, "local_path", event.target.value)} placeholder="C:\\models\\my-model.gguf" />
              </label>
              <label>
                Runtime
                <select value={profile.runtime_kind || "auto"} onChange={(event) => updateLlmProfile(index, "runtime_kind", event.target.value)}>
                  <option value="auto">Auto detect</option>
                  <option value="managed_local">Managed local</option>
                  <option value="remote_api">Remote API</option>
                </select>
              </label>
              <label>
                Context Window
                <input type="number" min="2048" value={profile.context_window || 32768} onChange={(event) => updateLlmProfile(index, "context_window", Number(event.target.value))} />
              </label>
              <label>
                Max Output Tokens
                <input type="number" min="256" value={profile.max_output_tokens || 1800} onChange={(event) => updateLlmProfile(index, "max_output_tokens", Number(event.target.value))} />
              </label>
              <label>
                Input Cost / 1M Tokens
                <input type="number" min="0" step="0.000001" value={profile.input_cost_per_million || 0} onChange={(event) => updateLlmProfile(index, "input_cost_per_million", Number(event.target.value))} />
              </label>
              <label>
                Output Cost / 1M Tokens
                <input type="number" min="0" step="0.000001" value={profile.output_cost_per_million || 0} onChange={(event) => updateLlmProfile(index, "output_cost_per_million", Number(event.target.value))} />
              </label>
              <label>
                Max Specialists
                <input type="number" min="0" max="16" value={profile.max_specialists ?? 2} onChange={(event) => updateLlmProfile(index, "max_specialists", Number(event.target.value))} />
              </label>
              <label className="checkbox-item"><input type="checkbox" checked={profile.supports_reasoning ?? true} onChange={(event) => updateLlmProfile(index, "supports_reasoning", event.target.checked)} /> Supports thinking</label>
              <label className="checkbox-item"><input type="checkbox" checked={profile.supports_parallel || false} onChange={(event) => updateLlmProfile(index, "supports_parallel", event.target.checked)} /> Parallel requests</label>
              {profile.supports_parallel ? <label>Max Parallel Requests<input type="number" min="1" max="32" value={profile.max_parallel_requests || 1} onChange={(event) => updateLlmProfile(index, "max_parallel_requests", Number(event.target.value))} /></label> : null}
            </div>
          </div>
        ))}
        </div>

        <div className="settings-block">
        <div className="panel-header">
          <h3>Embedding Profiles</h3>
          <button type="button" onClick={addEmbeddingProfile}>Add Embeddings</button>
        </div>
        {embeddingProfiles.map((profile, index) => (
          <div key={profile.id || index} className="settings-block">
            <div className="panel-header">
              <strong>{profile.label || `Embeddings ${index + 1}`}</strong>
              <button type="button" className="secondary-button" onClick={() => onChange({ ...settings, embedding_profiles: embeddingProfiles.filter((_, profileIndex) => profileIndex !== index) })}>
                Remove
              </button>
            </div>
            <div className="brief-grid">
              <label>
                Profile ID
                <input value={profile.id || ""} onChange={(event) => updateEmbeddingProfile(index, "id", event.target.value)} />
              </label>
              <label>
                Label
                <input value={profile.label || ""} onChange={(event) => updateEmbeddingProfile(index, "label", event.target.value)} />
              </label>
              <label>
                Model ID or Local Path
                <input value={profile.model_name || ""} onChange={(event) => updateEmbeddingProfile(index, "model_name", event.target.value)} placeholder="sentence-transformers/all-MiniLM-L6-v2" />
              </label>
            </div>
            <div className="preset-grid">
              {(config.embedding_model_presets || []).map((preset) => (
                <button key={`${profile.id}-${preset}`} type="button" className="preset-chip" onClick={() => updateEmbeddingProfile(index, "model_name", preset)}>
                  {preset}
                </button>
              ))}
            </div>
          </div>
        ))}
        </div>

        <div className="settings-block">
        <h3>Assignments</h3>
        <p className="muted">Advanced routing lives here. These assignments stay available when one project needs finer control than the top-level execution strategy.</p>
        <div className="assignment-groups">
          {[
            { title: "Layer 0", fields: ["layer0_plan", "layer0_extraction", "layer0_research"] },
            { title: "Generation", fields: ["layer1_generation", "layer2_generation", "layer3_generation"] },
            { title: "Research And Embeddings", fields: ["layer1_research", "layer2_research", "layer1_similarity_embeddings", "research_embeddings"] },
            { title: "Project Assistant", fields: ["assistant_orchestration", "assistant_synthesis", "assistant_compaction", "assistant_specialists", "assistant_embeddings"] },
          ].map((group) => (
            <div key={group.title} className="assignment-group">
              <h4>{group.title}</h4>
              <div className="brief-grid">
                {group.fields.map((key) => {
                  const label = LLM_ASSIGNMENT_LABELS[key] || EMBEDDING_ASSIGNMENT_LABELS[key];
                  const isLayer1Generation = key === "layer1_generation";
                  const isEmbeddingField = key in EMBEDDING_ASSIGNMENT_LABELS;
                  const options = isEmbeddingField ? embeddingProfiles : llmProfiles;
                  return (
                    <AssignmentField key={key} label={label} help={ASSIGNMENT_HELP[key]}>
                      {isLayer1Generation ? (
                        <div className="checkbox-grid">
                          {llmProfiles.map((profile) => (
                            <label key={`${key}-${profile.id}`} className="checkbox-item">
                              <input
                                type="checkbox"
                                checked={(assignments[key] || []).includes(profile.id)}
                                onChange={(event) => {
                                  const current = Array.isArray(assignments[key]) ? assignments[key] : [];
                                  if (event.target.checked) {
                                    updateAssignment(key, [...current, profile.id]);
                                    return;
                                  }
                                  updateAssignment(key, current.filter((item) => item !== profile.id));
                                }}
                              />
                              <span>{profile.label}</span>
                            </label>
                          ))}
                        </div>
                      ) : (
                        <select value={assignments[key] || ""} onChange={(event) => updateAssignment(key, event.target.value)}>
                          {options.map((profile) => (
                            <option key={profile.id} value={profile.id}>{profile.label}</option>
                          ))}
                        </select>
                      )}
                    </AssignmentField>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
        </div>
      </details>

      {savePlacement === "footer" ? (
        <div className="panel settings-save-bar">
          <div>
            <strong>Ready to apply project-specific behavior?</strong>
            <p className="muted">Save after reviewing compute mode, routing, and research behavior for this project.</p>
          </div>
          <button type="button" onClick={onSave} disabled={saveState === "saving"}>
            {saveState === "saving" ? "Saving..." : saveLabel}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function AppSettingsModal({ settings, config, saveState, onChange, onSave, onClose }) {
  // Modal wrapper for global defaults that seed future projects.
  return (
    <ModalFrame
      title="App Settings"
      subtitle="Manage reusable app defaults, model profiles, embeddings, and assignment routing for new projects."
      onClose={onClose}
      className="settings-modal"
    >
      <div className="tab-content">
        <ModelSettingsEditor
          settings={settings}
          config={config}
          saveState={saveState}
          onChange={onChange}
          onSave={onSave}
          title="App Defaults"
          description="These defaults seed new projects and act as the reusable baseline. Existing project overrides stay untouched unless you edit that project."
          saveLabel="Save App Settings"
          showRuntimeFields
        />
      </div>
    </ModalFrame>
  );
}

export function ProjectSettingsTab({ settings, config, saveState, onChange, onSave }) {
  // Project-scoped settings panel for overriding global model assignments.
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
        title="Project Model Overrides"
        description="These settings override the reusable app defaults only for this project."
        saveLabel="Save Project Overrides"
        showCompetitiveControl
        savePlacement="footer"
      />
    </section>
  );
}

