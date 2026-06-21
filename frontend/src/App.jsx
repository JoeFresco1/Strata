import { useEffect, useState } from "react";
import TreeDashboard from "./treeDashboard";
import Layer2GraphPanel, { CompetitiveIntelligencePanel } from "./Layer2GraphPanel";
import PromptCatalogEditor from "./PromptCatalogEditor";
import BriefWorkspace from "./BriefWorkspace";
import { AppSettingsModal, ProjectSettingsTab } from "./ModelSettingsPanel";
import { CreateProjectModal, GuideModal, ModalFrame, ProjectHub } from "./ProjectShell";
import { CheckboxList, GenerationSummary, MarketPanel, NodeEditor, ResearchStatus } from "./ReviewPanels";

const API_BASE = "http://127.0.0.1:8000/api";
const TABS = ["Layer 0", "Generate", "Review", "Competitive Intelligence", "Tree", "Specs", "Settings", "Export"];


// Fetch JSON from the local API and surface readable errors to the UI.
async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function sortProjects(projects, sortOrder) {
  // Keeps the project library ordering deterministic after refreshes.
  const copy = [...projects];
  copy.sort((left, right) => {
    const leftTime = new Date(left.created_at).getTime();
    const rightTime = new Date(right.created_at).getTime();
    return sortOrder === "oldest" ? leftTime - rightTime : rightTime - leftTime;
  });
  return copy;
}

// Keep only the items a human has approved for downward expansion.
function approvedNodes(nodes, nodeType) {
  return nodes.filter((node) => node.node_type === nodeType && ["kept", "prioritized"].includes(node.status));
}

// Build a label-to-id map for checkbox lists and selectors.
function choiceMap(nodes) {
  return Object.fromEntries(nodes.map((node) => [`${node.title} (${node.status})`, node.id]));
}

// Keep the localhost UI focused on fast end-to-end project work.
export default function App() {
  const [config, setConfig] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [snapshot, setSnapshot] = useState(null);
  const [appSettings, setAppSettings] = useState(null);
  const [projectModelSettings, setProjectModelSettings] = useState(null);
  const [activeTab, setActiveTab] = useState("Layer 0");
  const [statusMessage, setStatusMessage] = useState("Loading Strata...");
  const [error, setError] = useState("");
  const [lastSummary, setLastSummary] = useState(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectIdea, setNewProjectIdea] = useState("");
  const [sortOrder, setSortOrder] = useState("newest");
  const [navOpen, setNavOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [showPrompts, setShowPrompts] = useState(false);
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [modelSettingsSaveState, setModelSettingsSaveState] = useState("idle");
  const [projectSettingsSaveState, setProjectSettingsSaveState] = useState("idle");
  const [layer1Thinking, setLayer1Thinking] = useState(false);
  const [layer1MaxRounds, setLayer1MaxRounds] = useState(6);
  const [layer1TargetPerRound, setLayer1TargetPerRound] = useState(12);
  const [layer1MinNew, setLayer1MinNew] = useState(2);
  const [layer2Selected, setLayer2Selected] = useState([]);
  const [layer2Thinking, setLayer2Thinking] = useState(false);
  const [layer2MaxRounds, setLayer2MaxRounds] = useState(5);
  const [layer2TargetPerRound, setLayer2TargetPerRound] = useState(10);
  const [layer2MinNew, setLayer2MinNew] = useState(2);
  const [layer3Selected, setLayer3Selected] = useState([]);
  const [layer3Thinking, setLayer3Thinking] = useState(false);
  const [selectedSpecId, setSelectedSpecId] = useState("");

  // Load config and project list on first render.
  useEffect(() => {
  async function loadBootstrap() {
      try {
        const [configPayload, projectsPayload, healthPayload] = await Promise.all([
          apiFetch("/config"),
          apiFetch("/projects"),
          apiFetch("/health"),
        ]);
        setConfig(configPayload);
        setAppSettings(configPayload);
        setProjects(projectsPayload);
        setStatusMessage(
          healthPayload.ok
            ? "Local model ready."
            : "Local model offline. Generation and research will wait until llama.cpp is available.",
        );
        setActiveProjectId("");
      } catch (loadError) {
        setError(loadError.message);
      }
    }
    loadBootstrap();
  }, []);

  // Refresh the active project snapshot whenever the selected project changes.
  useEffect(() => {
    if (!activeProjectId) {
      setSnapshot(null);
      setProjectModelSettings(null);
      setActiveTab("Layer 0");
      return;
    }
    async function loadSnapshot() {
      try {
        const payload = await apiFetch(`/projects/${activeProjectId}`);
        applySnapshot(payload);
        setSelectedSpecId("");
      } catch (loadError) {
        setError(loadError.message);
      }
    }
    loadSnapshot();
  }, [activeProjectId]);

  // Refresh the project list after create/generation flows that might change ordering.
  async function refreshProjects() {
    const payload = await apiFetch("/projects");
    setProjects(payload);
  }

  // Replace the local snapshot after an API action.
  function applySnapshot(nextSnapshot) {
    setSnapshot(nextSnapshot);
    setProjectModelSettings(nextSnapshot?.project_model_settings || null);
  }

  // Create a new project from the homepage form.
  async function handleCreateProject(event) {
    event.preventDefault();
    setError("");
    const payload = await apiFetch("/projects", {
      method: "POST",
      body: JSON.stringify({
        name: newProjectName,
        idea: newProjectIdea,
      }),
    });
    await refreshProjects();
    setNewProjectName("");
    setNewProjectIdea("");
    setShowCreateProject(false);
    setActiveTab("Layer 0");
    setActiveProjectId(payload.id);
  }

  async function handleSaveModelSettings() {
    // Persists reusable defaults for future projects and runtime routing.
    if (!appSettings) {
      return;
    }
    setError("");
    setModelSettingsSaveState("saving");
    try {
      const payload = await apiFetch("/config/models", {
        method: "PATCH",
        body: JSON.stringify(appSettings),
      });
      setConfig(payload);
      setAppSettings(payload);
      setModelSettingsSaveState("saved");
      setStatusMessage(`Model settings updated. Chat model: ${payload.llm_model_name}. Embeddings: ${payload.embeddings_model_name}.`);
    } catch (saveError) {
      setModelSettingsSaveState("error");
      setError(saveError.message);
    }
  }

  async function handleSaveProjectModelSettings() {
    // Persists model assignments that apply only to the active project.
    if (!activeProjectId || !projectModelSettings) {
      return;
    }
    setError("");
    setProjectSettingsSaveState("saving");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/settings/models`, {
        method: "PATCH",
        body: JSON.stringify(projectModelSettings),
      });
      setProjectModelSettings(payload);
      applySnapshot({ ...snapshot, project_model_settings: payload });
      setProjectSettingsSaveState("saved");
      setStatusMessage("Project model assignments updated.");
    } catch (saveError) {
      setProjectSettingsSaveState("error");
      setError(saveError.message);
    }
  }

  // Save a node edit and then refresh the active snapshot.
  async function handleNodeSave(nodeId, payload) {
    setError("");
    try {
      await apiFetch(`/nodes/${nodeId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
      setStatusMessage("Node updated.");
    } catch (saveError) {
      setError(saveError.message);
      throw saveError;
    }
  }

  async function handleBriefSave(payload) {
    // Saves structured Layer 0 form edits without publishing the brief.
    setError("");
    try {
      await apiFetch(`/projects/${activeProjectId}/brief`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
    } catch (saveError) {
      setError(saveError.message);
    }
  }

  async function handlePlanChat(message) {
    // Sends conversational Layer 0 input and applies extracted brief updates.
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/brief/chat`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      applySnapshot({
        ...snapshot,
        brief: payload.brief,
        brief_conversation: payload.conversation,
      });
      return payload;
    } catch (chatError) {
      setError(chatError.message);
      throw chatError;
    }
  }

  async function handlePublishBrief() {
    // Locks Layer 0 for downstream generation and queues initial research.
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/brief/publish`, {
        method: "POST",
      });
      applySnapshot(payload.snapshot);
      setStatusMessage("Layer 0 published. Local competitor research queued.");
    } catch (publishError) {
      setError(publishError.message);
    }
  }

  async function handleRerunLayer0Research() {
    // Requeues project-level competitor discovery.
    setError("");
    try {
      await apiFetch(`/projects/${activeProjectId}/research/layer0`, { method: "POST" });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
      setStatusMessage("Layer 0 research queued.");
    } catch (researchError) {
      setError(researchError.message);
    }
  }

  async function handleRerunLayer1Research(pillarIds) {
    // Requeues pillar-specific research for selected or all Layer 1 pillars.
    setError("");
    try {
      await apiFetch(`/projects/${activeProjectId}/research/layer1`, {
        method: "POST",
        body: JSON.stringify({ pillar_ids: pillarIds }),
      });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
      setStatusMessage("Layer 1 research queued.");
    } catch (researchError) {
      setError(researchError.message);
    }
  }

  // Run Layer 1 broadening through the FastAPI backend.
  async function handleGenerateLayer1() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer1`, {
        method: "POST",
        body: JSON.stringify({
          model_aliases: [],
          thinking_enabled: layer1Thinking,
          max_rounds: layer1MaxRounds,
          target_per_round: layer1TargetPerRound,
          min_new_items_per_round: layer1MinNew,
          stale_rounds_to_stop: 2,
        }),
      });
      setLastSummary(payload.summary);
      applySnapshot(payload.snapshot);
      await refreshProjects();
    } catch (generationError) {
      setError(generationError.message);
    }
  }

  // Run graph-native Layer 2 generation for the selected kept pillars.
  async function handleGenerateLayer2() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer2`, {
        method: "POST",
        body: JSON.stringify({
          pillar_ids: layer2Selected,
          thinking_enabled: layer2Thinking,
          max_rounds: layer2MaxRounds,
          target_per_round: layer2TargetPerRound,
          min_new_items_per_round: layer2MinNew,
          stale_rounds_to_stop: 2,
        }),
      });
      setLastSummary({
        stop_reason: "layer2_graph_review_queue",
        total_rounds: layer2MaxRounds,
        created_nodes: payload.summary?.created_feature_ids || [],
        duplicate_candidates: payload.summary?.duplicate_recommendations || 0,
        filtered_candidates: payload.summary?.negative_cache_matches || 0,
        thinking_enabled: layer2Thinking,
        final_coverage_summary: `${payload.summary?.raw_candidate_count || 0} raw candidates, ${payload.summary?.review_queue_count || 0} items awaiting review.`,
        round_summaries: [],
      });
      applySnapshot(payload.snapshot);
    } catch (generationError) {
      setError(generationError.message);
    }
  }

  async function handleLayer2Review(action) {
    // Applies one human review action to the Layer 2 graph queue.
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/layer2/review`, {
        method: "POST",
        body: JSON.stringify(action),
      });
      applySnapshot(payload.snapshot);
      setStatusMessage(`Layer 2 action recorded: ${action.action_type}.`);
    } catch (reviewError) {
      setError(reviewError.message);
    }
  }

  async function handleLayer2FeatureCreate(payload) {
    // Adds a human-authored feature directly into the Layer 2 review queue.
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/layer2/features`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      applySnapshot(response.snapshot);
      setStatusMessage("Layer 2 feature added.");
    } catch (createError) {
      setError(createError.message);
      throw createError;
    }
  }

  async function handleLayer2FeatureUpdate(featureId, payload) {
    // Saves inline workbench edits without forcing a full generation pass.
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/layer2/features/${featureId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      applySnapshot(response.snapshot);
      setStatusMessage("Layer 2 feature updated.");
    } catch (updateError) {
      setError(updateError.message);
      throw updateError;
    }
  }

  async function handleLayer2BulkAction(payload) {
    // Applies the same review action to a selected feature set.
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/layer2/bulk`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      applySnapshot(response.snapshot);
      setStatusMessage(`Bulk Layer 2 action recorded: ${payload.action_type}.`);
    } catch (bulkError) {
      setError(bulkError.message);
      throw bulkError;
    }
  }

  async function handleLayer2Evidence(payload) {
    // Stores manual competitor evidence for feature-level research views.
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/layer2/evidence`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      applySnapshot(response.snapshot);
      setStatusMessage("Feature evidence added.");
    } catch (evidenceError) {
      setError(evidenceError.message);
      throw evidenceError;
    }
  }

  async function handleCompetitiveSettings(payload) {
    // Saves the competitor set used by the Layer 2 matrix.
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/competitive/layer2/settings`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      applySnapshot(response.snapshot);
      setStatusMessage("Competitive settings updated.");
    } catch (settingsError) {
      setError(settingsError.message);
      throw settingsError;
    }
  }

  // Run Layer 3 spec generation for the selected subfeatures.
  async function handleGenerateLayer3() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer3`, {
        method: "POST",
        body: JSON.stringify({
          subfeature_ids: layer3Selected,
          thinking_enabled: layer3Thinking,
        }),
      });
      setLastSummary({
        stop_reason: "completed",
        total_rounds: 1,
        created_nodes: payload.created,
        duplicate_candidates: 0,
        filtered_candidates: 0,
        thinking_enabled: layer3Thinking,
        round_summaries: [],
      });
      applySnapshot(payload.snapshot);
    } catch (generationError) {
      setError(generationError.message);
    }
  }

  // Trigger a project export and show the saved file paths.
  async function handleExport() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/export`, {
        method: "POST",
      });
      setStatusMessage(`Exported to ${payload.markdown_path} and ${payload.json_path}`);
    } catch (exportError) {
      setError(exportError.message);
    }
  }

  async function handleLayer2Export() {
    // Exports the reviewed Layer 2 graph separately from the full project tree.
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/export/layer2`, {
        method: "POST",
      });
      setStatusMessage(`Layer 2 exported to ${payload.markdown_path} and ${payload.json_path}`);
    } catch (exportError) {
      setError(exportError.message);
    }
  }

  if (!config) {
    return <div className="app-shell">Loading configuration...</div>;
  }

  const nodes = snapshot?.nodes || [];
  const tree = snapshot?.tree || [];
  const memories = snapshot?.memory || [];
  const brief = snapshot?.brief || null;
  const conversation = snapshot?.brief_conversation || [];
  const researchJobs = snapshot?.research_jobs || [];
  const researchFindings = snapshot?.research_findings || [];
  const layer2Graph = snapshot?.layer2_graph || {};
  const project = snapshot?.project || null;
  const pillarChoices = choiceMap(approvedNodes(nodes, "pillar"));
  const subfeatureChoices = choiceMap(approvedNodes(nodes, "subfeature"));
  const specs = nodes.filter((node) => node.node_type === "spec");
  const selectedSpec = specs.find((item) => item.id === selectedSpecId) || specs[0] || null;
  const quarantine = memories.find((item) => item.scope === "layer1" && item.memory_type === "quarantine");
  const layer1Enabled = brief?.status === "published";
  const sortedProjects = sortProjects(projects, sortOrder);

  return (
    <div className={navOpen ? "app-shell nav-open" : "app-shell"}>
      <aside className={navOpen ? "nav-rail open" : "nav-rail closed"}>
        <div className="nav-rail-top">
          <button
            type="button"
            className="rail-icon-button"
            aria-label={navOpen ? "Collapse menu" : "Open menu"}
            onClick={() => setNavOpen((current) => !current)}
          >
            <span className="hamburger-icon" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
          </button>
          {navOpen ? (
            <div className="brand-lockup">
              <strong>Strata</strong>
              <span className="muted">{statusMessage}</span>
            </div>
          ) : null}
        </div>
        {navOpen ? (
          <>
            <div className="nav-rail-actions">
              <button type="button" className="rail-action" onClick={() => setShowGuide(true)}>
                Guide
              </button>
              <button type="button" className="rail-action" onClick={() => setShowPrompts(true)}>
                System Prompts
              </button>
              <button type="button" className="rail-action" onClick={() => setShowSettings(true)}>
                Settings
              </button>
            </div>
            <div className="nav-rail-footer muted">
              <p>API: {API_BASE}</p>
              <p>DB: {config.database_backend}</p>
            </div>
          </>
        ) : null}
      </aside>

      <main className="main-content">
        {project ? (
          <div className="page-header">
            <div>
              <button type="button" className="ghost-button" onClick={() => setActiveProjectId("")}>
                Back To Library
              </button>
              <h2>{project.name}</h2>
              <p>{project.idea}</p>
            </div>
            {error ? <div className="error-banner">{error}</div> : null}
          </div>
        ) : error ? <div className="error-banner">{error}</div> : null}
        {!project ? (
          <ProjectHub
            projects={sortedProjects}
            sortOrder={sortOrder}
            onSortOrderChange={setSortOrder}
            onCreateProject={() => setShowCreateProject(true)}
            onOpenProject={(projectId) => {
              setActiveTab("Layer 0");
              setActiveProjectId(projectId);
            }}
          />
        ) : (
          <>
            <div className="tabs">
              {TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={tab === activeTab ? "tab active" : "tab"}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>

            {activeTab === "Layer 0" && brief ? (
              <section className="tab-content">
                <BriefWorkspace
                  brief={brief}
                  conversation={conversation}
                  onSave={handleBriefSave}
                  onChat={handlePlanChat}
                  onPublish={handlePublishBrief}
                />
                <ResearchStatus
                  jobs={researchJobs}
                  onRerunLayer0={handleRerunLayer0Research}
                  onRerunLayer1={handleRerunLayer1Research}
                />
                <MarketPanel findings={researchFindings} />
              </section>
            ) : null}

            {activeTab === "Generate" ? (
              <section className="tab-content">
                <div className="panel">
                  <h3>Layer 1 Broadening</h3>
                  <p className="muted">
                    {layer1Enabled
                      ? "Uses the Layer 1 assignment from this project's Settings tab."
                      : "Publish the Layer 0 brief before broadening Layer 1."}
                  </p>
                  <div className="field-row">
                    <label>
                      Thinking
                      <input type="checkbox" checked={layer1Thinking} onChange={(event) => setLayer1Thinking(event.target.checked)} />
                    </label>
                    <label>
                      Max Rounds
                      <input type="number" value={layer1MaxRounds} onChange={(event) => setLayer1MaxRounds(Number(event.target.value))} />
                    </label>
                    <label>
                      Target per Round
                      <input
                        type="number"
                        value={layer1TargetPerRound}
                        onChange={(event) => setLayer1TargetPerRound(Number(event.target.value))}
                      />
                    </label>
                    <label>
                      Min New
                      <input type="number" value={layer1MinNew} onChange={(event) => setLayer1MinNew(Number(event.target.value))} />
                    </label>
                  </div>
                  <button type="button" onClick={handleGenerateLayer1} disabled={!layer1Enabled}>
                    Broaden Layer 1
                  </button>
                </div>

                <CheckboxList
                  title="Layer 2 Eligible Pillars"
                  options={pillarChoices}
                  selectedValues={layer2Selected}
                  onChange={setLayer2Selected}
                />
                <div className="panel">
                  <h3>Layer 2 Broadening</h3>
                  <div className="field-row">
                    <label>
                      Thinking
                      <input type="checkbox" checked={layer2Thinking} onChange={(event) => setLayer2Thinking(event.target.checked)} />
                    </label>
                    <label>
                      Max Rounds
                      <input type="number" value={layer2MaxRounds} onChange={(event) => setLayer2MaxRounds(Number(event.target.value))} />
                    </label>
                    <label>
                      Target per Round
                      <input
                        type="number"
                        value={layer2TargetPerRound}
                        onChange={(event) => setLayer2TargetPerRound(Number(event.target.value))}
                      />
                    </label>
                    <label>
                      Min New
                      <input type="number" value={layer2MinNew} onChange={(event) => setLayer2MinNew(Number(event.target.value))} />
                    </label>
                  </div>
                  <button type="button" onClick={handleGenerateLayer2} disabled={!layer2Selected.length}>
                    Broaden Layer 2
                  </button>
                </div>
                <Layer2GraphPanel
                  graph={layer2Graph}
                  pillars={approvedNodes(nodes, "pillar")}
                  onReview={handleLayer2Review}
                  onCreateFeature={handleLayer2FeatureCreate}
                  onUpdateFeature={handleLayer2FeatureUpdate}
                  onBulkAction={handleLayer2BulkAction}
                  onAddEvidence={handleLayer2Evidence}
                />

                <CheckboxList
                  title="Layer 3 Eligible Subfeatures"
                  options={subfeatureChoices}
                  selectedValues={layer3Selected}
                  onChange={setLayer3Selected}
                />
                <div className="panel">
                  <h3>Layer 3 Specs</h3>
                  <label>
                    Thinking
                    <input type="checkbox" checked={layer3Thinking} onChange={(event) => setLayer3Thinking(event.target.checked)} />
                  </label>
                  <button type="button" onClick={handleGenerateLayer3} disabled={!layer3Selected.length}>
                    Generate Layer 3 Specs
                  </button>
                </div>
                <GenerationSummary summary={lastSummary} />
              </section>
            ) : null}

            {activeTab === "Tree" ? (
              <section className="tab-content">
                {tree.length || brief ? (
                  <TreeDashboard
                    project={project}
                    brief={brief}
                    tree={tree}
                    findings={researchFindings}
                    onSaveNode={handleNodeSave}
                  />
                ) : (
                  <div className="panel">
                    <h3>Product Map</h3>
                    <p className="muted">No generated nodes yet.</p>
                  </div>
                )}
              </section>
            ) : null}

            {activeTab === "Review" ? (
              <section className="tab-content">
                <Layer2GraphPanel
                  graph={layer2Graph}
                  pillars={approvedNodes(nodes, "pillar")}
                  onReview={handleLayer2Review}
                  onCreateFeature={handleLayer2FeatureCreate}
                  onUpdateFeature={handleLayer2FeatureUpdate}
                  onBulkAction={handleLayer2BulkAction}
                  onAddEvidence={handleLayer2Evidence}
                />
                {nodes.length ? nodes.map((node) => (
                  <NodeEditor
                    key={node.id}
                    node={node}
                    onSave={handleNodeSave}
                    findings={researchFindings}
                    onRerunResearch={handleRerunLayer1Research}
                  />
                )) : <p className="muted">Nothing to review yet.</p>}
              </section>
            ) : null}

            {activeTab === "Competitive Intelligence" ? (
              <CompetitiveIntelligencePanel
                graph={layer2Graph}
                pillars={approvedNodes(nodes, "pillar")}
                onCompetitiveSettings={handleCompetitiveSettings}
              />
            ) : null}

            {activeTab === "Specs" ? (
              <section className="tab-content">
                <div className="panel">
                  <h3>Spec Viewer</h3>
                  {selectedSpec ? (
                    <>
                      <label>
                        Spec
                        <select value={selectedSpec.id} onChange={(event) => setSelectedSpecId(event.target.value)}>
                          {specs.map((spec) => (
                            <option key={spec.id} value={spec.id}>
                              {spec.title}
                            </option>
                          ))}
                        </select>
                      </label>
                      <p>{selectedSpec.description}</p>
                      <pre>{JSON.stringify(selectedSpec.json_payload, null, 2)}</pre>
                    </>
                  ) : (
                    <p className="muted">No specs generated yet.</p>
                  )}
                </div>
              </section>
            ) : null}

            {activeTab === "Settings" ? (
              <ProjectSettingsTab
                settings={projectModelSettings}
                config={config}
                saveState={projectSettingsSaveState}
                onChange={setProjectModelSettings}
                onSave={handleSaveProjectModelSettings}
              />
            ) : null}

            {activeTab === "Export" ? (
              <section className="tab-content">
                <div className="panel">
                  <h3>Export</h3>
                  <div className="button-row">
                    <button type="button" onClick={handleExport}>
                      Export Markdown and JSON
                    </button>
                    <button type="button" onClick={handleLayer2Export}>
                      Export Layer 2 Markdown and JSON
                    </button>
                  </div>
                  {layer2Graph.review_open ? (
                    <p className="warning">Layer 2 export includes unresolved review state. Layer 3 still requires approved features.</p>
                  ) : null}
                </div>
                <div className="panel">
                  <h3>Generation Memory</h3>
                  <pre>{JSON.stringify(memories, null, 2)}</pre>
                </div>
                {quarantine ? (
                  <div className="panel">
                    <h3>Layer 1 Quarantine</h3>
                    <pre>{JSON.stringify(quarantine.content, null, 2)}</pre>
                  </div>
                ) : null}
              </section>
            ) : null}
          </>
        )}
      </main>
      {showCreateProject ? (
        <CreateProjectModal
          name={newProjectName}
          idea={newProjectIdea}
          onNameChange={setNewProjectName}
          onIdeaChange={setNewProjectIdea}
          onSubmit={handleCreateProject}
          onClose={() => setShowCreateProject(false)}
        />
      ) : null}
      {showSettings ? (
        <AppSettingsModal
          settings={appSettings}
          config={config}
          saveState={modelSettingsSaveState}
          onChange={setAppSettings}
          onSave={handleSaveModelSettings}
          onClose={() => setShowSettings(false)}
        />
      ) : null}
      {showPrompts ? (
        <ModalFrame
          title="System Prompts"
          subtitle="Edit the shared prompt templates here. These edits apply to new projects created after you save."
          onClose={() => setShowPrompts(false)}
          className="prompts-modal"
        >
          <PromptCatalogEditor
            settings={appSettings}
            onChange={setAppSettings}
            onSave={handleSaveModelSettings}
            saveState={modelSettingsSaveState}
          />
        </ModalFrame>
      ) : null}
      {showGuide ? <GuideModal onClose={() => setShowGuide(false)} /> : null}
    </div>
  );
}
