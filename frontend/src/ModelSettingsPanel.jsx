import { ModalFrame } from "./ProjectShell";

const LLM_ASSIGNMENT_LABELS = {
  layer0_plan: "Layer 0 Plan Chat",
  layer0_extraction: "Layer 0 Brief Extraction",
  layer1_generation: "Layer 1 Generation",
  layer2_generation: "Layer 2 Generation",
  layer3_generation: "Layer 3 Spec Generation",
  layer0_research: "Layer 0 Research Discovery",
  layer1_research: "Layer 1 Research Discovery",
};
const EMBEDDING_ASSIGNMENT_LABELS = {
  layer1_similarity_embeddings: "Layer 1 Similarity",
  research_embeddings: "Research Embeddings",
};
const ASSIGNMENT_HELP = {
  layer0_plan: "Use this model for the live Layer 0 intake conversation and brief shaping.",
  layer0_extraction: "Use this model to turn Plan mode messages into structured brief fields.",
  layer1_generation: "Use one or more models to brainstorm and broaden the Layer 1 pillar set.",
  layer2_generation: "Use this model to expand selected pillars into Layer 2 subfeatures.",
  layer3_generation: "Use this model to draft the final Layer 3 spec cards.",
  layer0_research: "Use this model to discover and summarize competitor evidence for Layer 0.",
  layer1_research: "Use this model to score how each Layer 1 pillar shows up across competitors.",
  layer1_similarity_embeddings: "Use this embedding model to measure overlap between Layer 1 pillars.",
  research_embeddings: "Use this embedding model to index research pages and compare evidence chunks.",
};

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

  // Appends a blank LLM profile row for user tuning.
  function addLlmProfile() {
    onChange({
      ...settings,
      llm_profiles: [
        ...llmProfiles,
        { id: `llm-${Date.now()}`, label: "New LLM", base_url: "", model_name: "", local_path: "" },
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
          <button type="button" onClick={onSave} disabled={saveState === "saving"}>
            {saveState === "saving" ? "Saving..." : saveLabel}
          </button>
        </div>
        <p className="muted">{description}</p>
      </div>

      {showRuntimeFields ? (
        <div className="panel">
          <h3>Runtime Defaults</h3>
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
          </div>
          <div className="preset-grid">
            {(config.embedding_model_presets || []).map((preset) => (
              <button key={preset} type="button" className="preset-chip" onClick={() => updateRootField("embeddings_model_name", preset)}>
                {preset}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="panel">
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
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
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

      <div className="panel">
        <h3>Assignments</h3>
        <div className="assignment-groups">
          {[
            { title: "Layer 0", fields: ["layer0_plan", "layer0_extraction", "layer0_research"] },
            { title: "Generation", fields: ["layer1_generation", "layer2_generation", "layer3_generation"] },
            { title: "Research And Embeddings", fields: ["layer1_research", "layer1_similarity_embeddings", "research_embeddings"] },
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
    </div>
  );
}

export function AppSettingsModal({ settings, config, saveState, onChange, onSave, onClose }) {
  // Modal wrapper for global defaults that seed future projects.
  return (
    <ModalFrame
      title="Settings"
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
      />
    </section>
  );
}

