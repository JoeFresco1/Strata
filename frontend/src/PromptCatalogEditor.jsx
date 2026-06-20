const PROMPT_FIELD_HELP = {
  system_json_generator: "Base system instruction for every structured JSON response.",
  layer0_brief_extraction: "Extracts brief field updates from Plan mode messages.",
  layer0_plan_guidance: "Shapes the short assistant reply and next questions in Plan mode.",
  layer1_pillar_generation: "Guides broad Layer 1 pillar brainstorming.",
  layer1_pillar_normalization: "Cleans raw Layer 1 ideas into stable pillar concepts.",
  layer1_pillar_assessment: "Scores and clusters candidate Layer 1 pillars.",
  layer1_pillar_research_assessment: "Rates how hard a pillar looks to build, run, and maintain after competitor research.",
  layer2_subfeature_generation: "Expands a pillar into Layer 2 subfeatures.",
  layer2_feature_graph_generation: "Runs scoped Layer 2 graph lens passes for concrete feature candidates.",
  layer2_scope_coverage_critic: "Assesses Layer 2 scope coverage, drift, and exhaustion.",
  layer2_integrity_critic: "Batched critic for granularity, out-of-bounds checks, and ambiguity scoring.",
  layer2_graph_critic: "Batched critic for duplicate directives, dependencies, and shared concern detection.",
  layer2_dynamic_coverage_family_discovery: "Finds the pillar-specific families that define Layer 2 exhaustion.",
  layer2_granularity_critic: "Flags candidates that are too broad, too narrow, or implementation-level.",
  layer2_overlap_dedupe_critic: "Finds duplicate and overlapping features within and across pillars.",
  layer2_shared_concern_critic: "Detects shared build concerns such as ingestion, notifications, permissions, or reporting.",
  layer2_ambiguity_critic: "Flags owner ambiguity, adjacent-pillar fit, and unclear scope placement.",
  layer2_negative_cache_critic: "Checks whether candidates resemble previously rejected Layer 2 concepts.",
  layer3_spec_generation: "Drafts the final Layer 3 implementation spec.",
  coverage_critic: "Summarizes overlap and saturation across generation loops.",
  json_schema_repair: "Repairs near-miss model output into valid JSON.",
};
const PROMPT_GROUPS = [
  {
    title: "Shared Core",
    description: "Prompts that power every layer, plus the JSON repair fallback.",
    fields: ["system_json_generator", "json_schema_repair"],
  },
  {
    title: "Layer 0",
    description: "Planning and brief-intake prompts used before publish.",
    fields: ["layer0_brief_extraction", "layer0_plan_guidance"],
  },
  {
    title: "Layer 1",
    description: "Pillar generation, normalization, assessment, and research review.",
    fields: [
      "layer1_pillar_generation",
      "layer1_pillar_normalization",
      "layer1_pillar_assessment",
      "layer1_pillar_research_assessment",
    ],
  },
  {
    title: "Layer 2",
    description: "Subfeature expansion prompts used after a pillar is selected.",
    fields: ["layer2_subfeature_generation", "layer2_feature_graph_generation"],
  },
  {
    title: "Layer 2 Sub-Agents",
    description: "Tunable critic prompts for exhaustion, overlap, shared concerns, ambiguity, and rejection memory.",
    fields: [
      "layer2_dynamic_coverage_family_discovery",
      "layer2_integrity_critic",
      "layer2_graph_critic",
      "layer2_scope_coverage_critic",
      "layer2_granularity_critic",
      "layer2_overlap_dedupe_critic",
      "layer2_shared_concern_critic",
      "layer2_ambiguity_critic",
      "layer2_negative_cache_critic",
    ],
  },
  {
    title: "Layer 3",
    description: "Final implementation-spec drafting prompts.",
    fields: ["layer3_spec_generation"],
  },
  {
    title: "Review",
    description: "Coverage critic prompts that watch for repetition and saturation.",
    fields: ["coverage_critic"],
  },
];

// Groups editable prompt templates by layer so tuning does not require scanning one long list.
function PromptCatalogEditor({ settings, onChange, onSave, saveState }) {
  if (!settings) {
    return (
      <div className="panel">
        <p className="muted">Prompts are loading.</p>
      </div>
    );
  }

  const promptCatalog = settings.prompt_catalog || {};
  const promptEntries = Object.entries(promptCatalog);
  const groupedPrompts = PROMPT_GROUPS.map((group) => ({
    ...group,
    entries: group.fields
      .map((key) => [key, promptCatalog[key]])
      .filter(([, value]) => typeof value === "string"),
  })).filter((group) => group.entries.length);

  const groupedKeys = new Set(PROMPT_GROUPS.flatMap((group) => group.fields));
  const ungroupedEntries = promptEntries.filter(([key]) => !groupedKeys.has(key));
  if (ungroupedEntries.length) {
    groupedPrompts.push({
      title: "Other",
      description: "Prompt templates that do not currently map to a specific layer group.",
      entries: ungroupedEntries,
    });
  }

  // Updates one prompt while preserving every other project/app setting.
  function updatePrompt(key, value) {
    onChange({
      ...settings,
      prompt_catalog: {
        ...promptCatalog,
        [key]: value,
      },
    });
  }

  return (
    <div className="prompt-editor">
      <div className="panel prompt-editor-header">
        <div>
          <h3>System Prompt Catalog</h3>
          <p className="muted">
            Changes here only affect projects created after you save. Existing projects keep the prompt snapshot they already have.
          </p>
        </div>
        <button type="button" onClick={onSave} disabled={saveState === "saving"}>
          {saveState === "saving" ? "Saving..." : "Save Prompts"}
        </button>
      </div>

      <div className="prompt-sections">
        {groupedPrompts.map((group) => (
          <section key={group.title} className="prompt-section panel">
            <div className="panel-header prompt-section-header">
              <div>
                <h4>{group.title}</h4>
                <p className="muted">{group.description}</p>
              </div>
              <span className="status-pill">{group.entries.length} prompt{group.entries.length === 1 ? "" : "s"}</span>
            </div>
            <div className="prompt-grid">
              {group.entries.map(([key, value]) => (
                <div key={key} className="panel prompt-card">
                  <div className="prompt-card-header">
                    <div>
                      <h4>{key}</h4>
                      <p className="muted">{PROMPT_FIELD_HELP[key] || "Editable template used by the local generation pipeline."}</p>
                    </div>
                  </div>
                  <textarea
                    className="prompt-textarea"
                    value={value}
                    onChange={(event) => updatePrompt(key, event.target.value)}
                    rows={10}
                  />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}


export default PromptCatalogEditor;
