import { useMemo, useState } from "react";

const PROMPT_FIELD_HELP = {
  system_json_generator: "Base system instruction for every structured JSON response.",
  layer0_brief_extraction: "Extracts brief field updates from Plan mode messages.",
  layer0_plan_guidance: "Shapes the short assistant reply and next questions in Plan mode.",
  layer0_conversation_response: "Shapes the streamed user-facing Layer 0 conversation response.",
  product_discovery_generation_v1: "Generates the versioned structured Product Discovery artifact from a published brief.",
  competitor_evidence_extraction_v1: "Extracts attributable competitor findings from retained source text.",
  competitor_pillar_inference_v1: "Infers competitor product territories with explicit evidence links and confidence.",
  competitor_strategic_comparison_v1: "Builds advisory competitive territories, gaps, and derived lenses.",
  layer1_pillar_generation: "Guides broad Layer 1 pillar brainstorming.",
  layer1_pillar_normalization: "Cleans raw Layer 1 ideas into stable pillar concepts.",
  layer1_pillar_assessment: "Scores and clusters candidate Layer 1 pillars.",
  layer1_pillar_research_assessment: "Rates how hard a pillar looks to build, run, and maintain after competitor research.",
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
  coverage_critic: "Summarizes overlap and saturation across generation loops.",
  json_schema_repair: "Repairs near-miss model output into valid JSON.",
  assistant_query_planner: "Plans allowlisted retrieval and specialist work for a project question.",
  assistant_specialist: "Runs bounded evidence analysis for Deep mode and complex questions.",
  assistant_synthesis: "Synthesizes the grounded answer, citations, and action previews.",
  assistant_compaction: "Compresses older turns while preserving decisions and unresolved work.",
};
const PROMPT_GROUPS = [
  {
    title: "Shared Core",
    tabLabel: "Core",
    description: "Prompts that power every layer, plus the JSON repair fallback.",
    fields: ["system_json_generator", "json_schema_repair"],
  },
  {
    title: "Layer 0",
    tabLabel: "Layer 0",
    description: "Planning and brief-intake prompts used before publish.",
    fields: ["layer0_brief_extraction", "layer0_plan_guidance", "layer0_conversation_response"],
  },
  {
    title: "Layer 1",
    tabLabel: "Layer 1",
    description: "Pillar generation, normalization, assessment, and research review.",
    fields: [
      "layer1_pillar_generation",
      "layer1_pillar_normalization",
      "layer1_pillar_assessment",
      "layer1_pillar_research_assessment",
    ],
  },
  {
    title: "Product Discovery",
    tabLabel: "Discovery",
    description: "Structured product exploration and evidence-bound competitor extraction before Layer 1.",
    fields: [
      "product_discovery_generation_v1",
      "competitor_evidence_extraction_v1",
      "competitor_pillar_inference_v1",
      "competitor_strategic_comparison_v1",
    ],
  },
  {
    title: "Layer 2",
    tabLabel: "Layer 2",
    description: "Feature graph generation and critic prompts for coverage, overlap, ambiguity, and rejection memory.",
    fields: [
      "layer2_feature_graph_generation",
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
    title: "Project Assistant",
    tabLabel: "Assistant",
    description: "Prompts for retrieval planning, specialists, response synthesis, and durable compaction.",
    fields: ["assistant_query_planner", "assistant_specialist", "assistant_synthesis", "assistant_compaction"],
  },
  {
    title: "Review",
    tabLabel: "Review",
    description: "Coverage critic prompts that watch for repetition and saturation.",
    fields: ["coverage_critic"],
  },
];

const PROMPT_EDITING_RULES = [
  {
    title: "Affects new projects",
    body: "Prompt edits update the reusable defaults that future projects inherit after save.",
  },
  {
    title: "Existing projects keep snapshots",
    body: "Current project runs keep their stored prompt catalog unless that project is recreated or otherwise reset.",
  },
  {
    title: "Group by workflow stage",
    body: "Review one layer at a time instead of trying to reason about the full catalog as a single blob.",
  },
];

const DEFAULT_ACTIVE_GROUP = "Layer 1";

// Presents one editable prompt at a time so tuning does not require scanning one long list.
function PromptCatalogEditor({ settings, onChange, onSave, saveState }) {
  const [activeGroupTitle, setActiveGroupTitle] = useState(DEFAULT_ACTIVE_GROUP);
  const [activePromptKey, setActivePromptKey] = useState("");

  const promptCatalog = settings?.prompt_catalog || {};
  const promptEntries = Object.entries(promptCatalog);
  const promptCount = promptEntries.length;
  const groupedPrompts = useMemo(() => {
    const groups = PROMPT_GROUPS.map((group) => ({
      ...group,
      entries: group.fields
        .map((key) => [key, promptCatalog[key]])
        .filter(([, value]) => typeof value === "string"),
    })).filter((group) => group.entries.length);

    const groupedKeys = new Set(PROMPT_GROUPS.flatMap((group) => group.fields));
    const ungroupedEntries = promptEntries.filter(([key]) => !groupedKeys.has(key));
    if (ungroupedEntries.length) {
      groups.push({
        title: "Other",
        tabLabel: "Other",
        description: "Prompt templates that do not currently map to a specific layer group.",
        entries: ungroupedEntries,
      });
    }
    return groups;
  }, [promptCatalog, promptEntries]);

  const activeGroup =
    groupedPrompts.find((group) => group.title === activeGroupTitle) ||
    groupedPrompts[0];
  const selectedPrompt =
    activeGroup?.entries.find(([key]) => key === activePromptKey) ||
    activeGroup?.entries[0];
  const selectedPromptKey = selectedPrompt?.[0] || "";
  const selectedPromptValue = selectedPrompt?.[1] || "";

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

  function selectGroup(group) {
    setActiveGroupTitle(group.title);
    setActivePromptKey(group.entries[0]?.[0] || "");
  }

  if (!settings) {
    return (
      <div className="panel">
        <p className="muted">Prompts are loading.</p>
      </div>
    );
  }

  return (
    <div className="prompt-editor">
      <div className="panel prompt-editor-header">
        <div className="prompt-editor-heading">
          <h3>System Prompt Catalog</h3>
          <p className="muted">
            Changes here only affect projects created after you save. Existing projects keep the prompt snapshot they already have.
          </p>
          <div className="prompt-summary-grid" aria-label="Prompt catalog summary">
            <div className="prompt-summary-card">
              <span>Templates</span>
              <strong>{promptCount}</strong>
            </div>
            <div className="prompt-summary-card">
              <span>Open tab</span>
              <strong>{activeGroup?.tabLabel || "None"}</strong>
            </div>
            <div className="prompt-summary-card">
              <span>Visible prompts</span>
              <strong>{activeGroup?.entries.length || 0}</strong>
            </div>
          </div>
        </div>
        <button type="button" onClick={onSave} disabled={saveState === "saving"}>
          {saveState === "saving" ? "Saving..." : "Save Prompts"}
        </button>
      </div>

      <section className="panel prompt-guidance compact">
        <div>
          <span className="guide-eyebrow">Editing guidance</span>
          <h3>Reusable defaults catalog</h3>
        </div>
        <div className="prompt-guidance-grid">
          {PROMPT_EDITING_RULES.map((rule) => (
            <div key={rule.title} className="prompt-guidance-card">
              <strong>{rule.title}</strong>
              <p className="muted">{rule.body}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="prompt-layer-tabs" role="tablist" aria-label="Prompt layers">
        {groupedPrompts.map((group) => (
          <button
            key={group.title}
            type="button"
            role="tab"
            aria-selected={group.title === activeGroup?.title}
            className={group.title === activeGroup?.title ? "active" : ""}
            onClick={() => selectGroup(group)}
          >
            <span>{group.tabLabel || group.title}</span>
            <strong>{group.entries.length}</strong>
          </button>
        ))}
      </div>

      {activeGroup ? (
        <section className="panel prompt-workbench" aria-labelledby="active-prompt-group">
          <div className="prompt-workbench-header">
            <div>
              <span className="guide-eyebrow">Prompt group</span>
              <h4 id="active-prompt-group">{activeGroup.title}</h4>
              <p className="muted">{activeGroup.description}</p>
            </div>
            <span className="status-pill">{activeGroup.entries.length} prompt{activeGroup.entries.length === 1 ? "" : "s"}</span>
          </div>

          <div className="prompt-workbench-body">
            <nav className="prompt-picker" aria-label={`${activeGroup.title} prompts`}>
              {activeGroup.entries.map(([key, value]) => (
                <button
                  key={key}
                  type="button"
                  className={key === selectedPromptKey ? "active" : ""}
                  onClick={() => setActivePromptKey(key)}
                >
                  <span>{key}</span>
                  <small>{value.trim().split(/\s+/).filter(Boolean).length} words</small>
                </button>
              ))}
            </nav>

            <div className="prompt-detail">
              {selectedPromptKey ? (
                <>
                  <div className="prompt-detail-header">
                    <div>
                      <span className="guide-eyebrow">Editing prompt</span>
                      <h4>{selectedPromptKey}</h4>
                      <p className="muted">{PROMPT_FIELD_HELP[selectedPromptKey] || "Editable template used by the local generation pipeline."}</p>
                    </div>
                    <span className="status-pill">{selectedPromptValue.length.toLocaleString()} chars</span>
                  </div>
                  <textarea
                    className="prompt-textarea"
                    aria-label={`${selectedPromptKey} prompt template`}
                    value={selectedPromptValue}
                    onChange={(event) => updatePrompt(selectedPromptKey, event.target.value)}
                    rows={18}
                  />
                </>
              ) : (
                <p className="muted">No prompt templates are available in this group.</p>
              )}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}


export default PromptCatalogEditor;
