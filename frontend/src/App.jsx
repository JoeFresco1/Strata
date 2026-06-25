import { useEffect, useMemo, useRef, useState } from "react";
import { CompetitiveIntelligencePanel } from "./Layer2GraphPanel";
import { API_BASE, apiFetch, subscribeApiActivity } from "./apiClient";
import { TABS, applyAssistantNavigation, approvedNodes, assistantScopeFor, findWorkspaceEntity, sortProjects } from "./appUtils";
import PromptCatalogEditor from "./PromptCatalogEditor";
import BriefWorkspace from "./BriefWorkspace";
import AssistantDrawer from "./AssistantDrawer";
import LivingWorkspace from "./LivingWorkspace";
import Layer3Workspace from "./Layer3Workspace";
import { buildWorkspaceTree } from "./projectWorkspaceData";
import { AppSettingsModal, ProjectSettingsTab } from "./ModelSettingsPanel";
import { CreateProjectModal, GuideModal, ModalFrame, ProjectHub } from "./ProjectShell";
import { GenerationSummary, MarketPanel, ResearchStatus } from "./ReviewPanels";
export default function App() {
  const [config, setConfig] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [snapshot, setSnapshot] = useState(null);
  const [appSettings, setAppSettings] = useState(null);
  const [projectModelSettings, setProjectModelSettings] = useState(null);
  const [activeTab, setActiveTab] = useState("Workspace");
  const [workspaceState, setWorkspaceState] = useState(null);
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
  const [layer2Thinking, setLayer2Thinking] = useState(false);
  const [layer2MaxRounds, setLayer2MaxRounds] = useState(5);
  const [layer2TargetPerRound, setLayer2TargetPerRound] = useState(10);
  const [layer2MinNew, setLayer2MinNew] = useState(2);
  const [layer3Thinking, setLayer3Thinking] = useState(false);
  const [lastExport, setLastExport] = useState(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [projectLoading, setProjectLoading] = useState(false);
  const [pendingMutations, setPendingMutations] = useState(0);
  const savedWorkspaceStates = useRef(new Map());
  const workspaceSaveQueue = useRef(Promise.resolve());

  useEffect(() => subscribeApiActivity(setPendingMutations), []);

  // Load config and project list on first render.
  useEffect(() => {
    let active = true;
    async function loadBootstrap() {
      setBootstrapLoading(true);
      try {
        const [configPayload, projectsPayload, healthPayload] = await Promise.all([
          apiFetch("/config"),
          apiFetch("/projects"),
          apiFetch("/health"),
        ]);
        if (!active) return;
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
        if (active) setError(loadError.message);
      } finally {
        if (active) setBootstrapLoading(false);
      }
    }
    loadBootstrap();
    return () => {
      active = false;
    };
  }, []);

  // Refresh the active project snapshot whenever the selected project changes.
  useEffect(() => {
    if (!activeProjectId) {
      setSnapshot(null);
      setProjectModelSettings(null);
      setWorkspaceState(null);
      setLastExport(null);
      setActiveTab("Workspace");
      setProjectLoading(false);
      return;
    }
    let active = true;
    async function loadSnapshot() {
      setProjectLoading(true);
      setSnapshot(null);
      try {
        setLastExport(null);
        const payload = await apiFetch(`/projects/${activeProjectId}`);
        if (!active) return;
        applySnapshot(payload);
        setWorkspaceState(payload.workspace_state);
        savedWorkspaceStates.current.set(activeProjectId, JSON.stringify(payload.workspace_state || {}));
        setActiveTab("Workspace");
      } catch (loadError) {
        if (active) setError(loadError.message);
      } finally {
        if (active) setProjectLoading(false);
      }
    }
    loadSnapshot();
    return () => {
      active = false;
    };
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId || !workspaceState) return undefined;
    const serializedState = JSON.stringify(workspaceState);
    if (serializedState === savedWorkspaceStates.current.get(activeProjectId)) return undefined;
    const timer = window.setTimeout(async () => {
      workspaceSaveQueue.current = workspaceSaveQueue.current.then(() => apiFetch(`/projects/${activeProjectId}/workspace-state`, {
          method: "PATCH",
          silent: true,
          body: JSON.stringify({
            view_mode: workspaceState.view_mode || "map",
            selected_entity_type: workspaceState.selected_entity_type || "brief",
            selected_entity_id: workspaceState.selected_entity_id || "layer0-root",
            table_scope: workspaceState.table_scope || "focused",
            map_state: workspaceState.map_state || {},
            table_state: workspaceState.table_state || {},
          }),
        })).then(() => {
        savedWorkspaceStates.current.set(activeProjectId, serializedState);
      }).catch((stateError) => {
        setError(stateError.message);
      });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [activeProjectId, workspaceState]);

  // Poll only while background research is active so progress and completed evidence appear automatically.
  useEffect(() => {
    const hasActiveResearch = (snapshot?.research_jobs || []).some((job) => ["queued", "running"].includes(job.status));
    if (!activeProjectId || !hasActiveResearch) return undefined;
    let cancelled = false;
    let timer;
    async function pollResearch() {
      if (document.visibilityState === "hidden") {
        timer = window.setTimeout(pollResearch, 3000);
        return;
      }
      try {
        const payload = await apiFetch(`/projects/${activeProjectId}`, { force: true });
        if (!cancelled) applySnapshot(payload);
      } catch (pollError) {
        if (!cancelled) setError(pollError.message);
      }
      if (!cancelled) timer = window.setTimeout(pollResearch, 2000);
    }
    timer = window.setTimeout(pollResearch, 2000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeProjectId, snapshot?.research_jobs]);

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
    setActiveTab("Workspace");
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

  async function handlePlanChat(message, requestId) {
    // Sends conversational Layer 0 input and applies extracted brief updates.
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/brief/chat`, {
        method: "POST",
        body: JSON.stringify({ message, request_id: requestId }),
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
  async function handleGenerateLayer2(pillarIds = []) {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer2`, {
        method: "POST",
        body: JSON.stringify({
          pillar_ids: pillarIds,
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
      setStatusMessage("Layer 2 generated. Full feature research queued automatically.");
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

  async function handleBulkNodeStatus(nodeIds, status) {
    await Promise.all(nodeIds.map((nodeId) => apiFetch(`/nodes/${nodeId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    })));
    applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
  }

  async function handleBulkFeatureStatus(featureIds, status) {
    const action_type = status === "prioritized" ? "prioritize" : status === "kept" ? "keep" : status;
    await Promise.all(featureIds.map((featureId) => apiFetch(`/projects/${activeProjectId}/layer2/review`, {
      method: "POST",
      body: JSON.stringify({
        action_type,
        feature_id: featureId,
        payload: action_type === "prioritize" ? { priority: "high" } : {},
      }),
    })));
    applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
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

  async function handleLayer2Research(featureIds = []) {
    // Queues selected features or the complete active Layer 2 review set for local research.
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/research/layer2`, {
        method: "POST",
        body: JSON.stringify({ feature_ids: featureIds }),
      });
      applySnapshot({
        ...snapshot,
        research_jobs: [response.job, ...(snapshot?.research_jobs || [])],
      });
      setStatusMessage(featureIds.length ? `Research queued for ${featureIds.length} selected features.` : "Full Layer 2 research queued.");
    } catch (researchError) {
      setError(researchError.message);
      throw researchError;
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

  // Generate complete or selectively refreshed Capability Design Cards.
  async function handleGenerateLayer3(featureIds, selectedSections = []) {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer3`, {
        method: "POST",
        body: JSON.stringify({
          feature_ids: featureIds,
          thinking_enabled: layer3Thinking,
          selected_sections: selectedSections,
        }),
      });
      applySnapshot(payload.snapshot);
      setStatusMessage(`Layer 3 updated ${payload.created.length} Capability Design Card${payload.created.length === 1 ? "" : "s"}.`);
    } catch (generationError) {
      setError(generationError.message);
      throw generationError;
    }
  }

  async function runLayer3Mutation(request, successMessage) {
    // Route Layer 3 mutations through the shared app error banner and snapshot refresh.
    setError("");
    try {
      const response = await request();
      if (response.snapshot) applySnapshot(response.snapshot);
      setStatusMessage(successMessage);
      return response;
    } catch (mutationError) {
      setError(mutationError.message);
      throw mutationError;
    }
  }

  async function handleLayer3Save(cardId, payload) {
    // Persist human edits without replacing untouched card sections.
    return runLayer3Mutation(
      () => apiFetch(`/projects/${activeProjectId}/layer3/cards/${cardId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
      "Capability Design Card saved.",
    );
  }

  async function handleLayer3Review(cardId, action) {
    // Apply the explicit Layer 3 human review gate.
    return runLayer3Mutation(
      () => apiFetch(`/projects/${activeProjectId}/layer3/cards/${cardId}/review`, {
        method: "POST",
        body: JSON.stringify({ action }),
      }),
      `Capability Design Card marked ${action}.`,
    );
  }

  async function handleLayer3PressureTest(cardId) {
    // Refresh readiness after human edits without regenerating card content.
    return runLayer3Mutation(
      () => apiFetch(`/projects/${activeProjectId}/layer3/cards/${cardId}/pressure-test`, {
        method: "POST",
        body: JSON.stringify({ thinking_enabled: layer3Thinking }),
      }),
      "Capability Design pressure test updated.",
    );
  }

  async function handleLayer3Decision(decisionId, status, resolution) {
    // Resolve or reopen one downstream product decision.
    return runLayer3Mutation(
      () => apiFetch(`/projects/${activeProjectId}/layer3/decisions/${decisionId}`, {
        method: "PATCH",
        body: JSON.stringify({ status, resolution }),
      }),
      `Layer 3 decision marked ${status}.`,
    );
  }

  async function handleLayer3Export() {
    // Write approved cards as a structured downstream agent manifest.
    const payload = await runLayer3Mutation(
      () => apiFetch(`/projects/${activeProjectId}/export/layer3`, { method: "POST" }),
      "Layer 3 manifest exported.",
    );
    setLastExport({ kind: "Layer 3", markdown_path: "", ...payload });
    setStatusMessage(`Layer 3 manifest exported to ${payload.json_path}`);
  }

  // Trigger a project export and show the saved file paths.
  async function handleExport() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/export`, {
        method: "POST",
      });
      setLastExport({ kind: "Full project", ...payload });
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
      setLastExport({ kind: "Layer 2", ...payload });
      setStatusMessage(`Layer 2 exported to ${payload.markdown_path} and ${payload.json_path}`);
    } catch (exportError) {
      setError(exportError.message);
    }
  }

  const nodes = snapshot?.nodes || [];
  const tree = snapshot?.tree || [];
  const memories = snapshot?.memory || [];
  const brief = snapshot?.brief || null;
  const conversation = snapshot?.brief_conversation || [];
  const researchJobs = snapshot?.research_jobs || [];
  const researchFindings = snapshot?.research_findings || [];
  const layer2Graph = snapshot?.layer2_graph || {};
  const layer3 = snapshot?.layer3 || {};
  const project = snapshot?.project || null;
  const quarantine = memories.find((item) => item.scope === "layer1" && item.memory_type === "quarantine");
  const layer1Enabled = brief?.status === "published";
  const sortedProjects = sortProjects(projects, sortOrder);
  const workspaceTree = useMemo(
    () => buildWorkspaceTree(project, brief, nodes, layer2Graph),
    [project, brief, nodes, layer2Graph],
  );
  const selectedWorkspaceEntity = useMemo(
    () => findWorkspaceEntity(workspaceTree, workspaceState?.selected_entity_id),
    [workspaceTree, workspaceState?.selected_entity_id],
  );
  const assistantScope = assistantScopeFor(activeTab, selectedWorkspaceEntity);

  if (bootstrapLoading && !config) {
    return <div className="app-loading-screen"><div className="loading-spinner" /><strong>Loading Strata</strong><span>Connecting to the local workspace...</span></div>;
  }

  if (!config) {
    return <div className="app-loading-screen"><strong>Strata could not load.</strong><span>{error || "The local API is unavailable."}</span><button type="button" onClick={() => window.location.reload()}>Retry</button></div>;
  }

  function navigateFromAssistant(layer, citation = {}) {
    applyAssistantNavigation({ layer, citation, setActiveTab, setWorkspaceState });
  }

  return (
    <div className={navOpen ? "app-shell nav-open" : "app-shell"}>
      {pendingMutations > 0 ? (
        <div className="network-activity" role="status">
          <span className="loading-spinner" />
          <span>{pendingMutations === 1 ? "Saving or running work..." : `${pendingMutations} operations in progress...`}</span>
        </div>
      ) : null}
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
            <button type="button" className="assistant-open-button" onClick={() => setAssistantOpen(true)}>
              Assistant
            </button>
            {error ? <div className="error-banner">{error}</div> : null}
          </div>
        ) : error ? <div className="error-banner">{error}</div> : null}
        {!activeProjectId ? (
          <ProjectHub
            projects={sortedProjects}
            loading={bootstrapLoading}
            sortOrder={sortOrder}
            onSortOrderChange={setSortOrder}
            onCreateProject={() => setShowCreateProject(true)}
            onOpenProject={(projectId) => {
              setActiveTab("Workspace");
              setActiveProjectId(projectId);
            }}
          />
        ) : projectLoading ? (
          <div className="project-loading-state" aria-live="polite">
            <div className="loading-spinner" />
            <div>
              <strong>Opening project</strong>
              <p className="muted">Loading the brief, workspace, research, and model settings.</p>
            </div>
          </div>
        ) : project && snapshot ? (
          <>
            <div className="tabs">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={tab.id === activeTab ? "tab active" : "tab"}
                  onClick={() => setActiveTab(tab.id)}
                >
                  {tab.label}
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
                <details className="panel quiet-details">
                  <summary>Research and market evidence</summary>
                  <ResearchStatus
                    jobs={researchJobs}
                    onRerunLayer0={handleRerunLayer0Research}
                    onRerunLayer1={handleRerunLayer1Research}
                  />
                  <MarketPanel findings={researchFindings} />
                </details>
              </section>
            ) : null}

            {activeTab === "Workspace" ? (
              <section className="tab-content">
                <LivingWorkspace
                  project={project}
                  brief={brief}
                  tree={workspaceTree}
                  layer2Graph={layer2Graph}
                  findings={researchFindings}
                  researchJobs={researchJobs}
                  workspaceState={workspaceState}
                  onWorkspaceStateChange={setWorkspaceState}
                  onSaveBrief={handleBriefSave}
                  onPublishBrief={handlePublishBrief}
                  onSaveNode={handleNodeSave}
                  onUpdateFeature={handleLayer2FeatureUpdate}
                  onCreateFeature={handleLayer2FeatureCreate}
                  onReviewFeature={handleLayer2Review}
                  onAddEvidence={handleLayer2Evidence}
                  onResearchLayer1={handleRerunLayer1Research}
                  onResearchLayer2={handleLayer2Research}
                  onGenerateLayer1={handleGenerateLayer1}
                  onGenerateLayer2={handleGenerateLayer2}
                  onBulkFeatureStatus={handleBulkFeatureStatus}
                  onBulkNodeStatus={handleBulkNodeStatus}
                  generationControls={{
                    layer1Thinking, setLayer1Thinking,
                    layer1MaxRounds, setLayer1MaxRounds,
                    layer1TargetPerRound, setLayer1TargetPerRound,
                    layer1MinNew, setLayer1MinNew,
                    layer2Thinking, setLayer2Thinking,
                    layer2MaxRounds, setLayer2MaxRounds,
                    layer2TargetPerRound, setLayer2TargetPerRound,
                    layer2MinNew, setLayer2MinNew,
                  }}
                />
                <GenerationSummary summary={lastSummary} />
              </section>
            ) : null}

            {activeTab === "Specs" ? (
              <section className="tab-content">
                <Layer3Workspace
                  layer3={layer3}
                  thinkingEnabled={layer3Thinking}
                  onThinkingChange={setLayer3Thinking}
                  onGenerate={handleGenerateLayer3}
                  onSave={handleLayer3Save}
                  onReview={handleLayer3Review}
                  onPressureTest={handleLayer3PressureTest}
                  onDecision={handleLayer3Decision}
                  onExport={handleLayer3Export}
                />
              </section>
            ) : null}

            {activeTab === "Project" ? (
              <section className="tab-content">
                <details className="panel project-tool-section" open>
                  <summary>Project settings</summary>
                  <ProjectSettingsTab
                    settings={projectModelSettings}
                    config={config}
                    saveState={projectSettingsSaveState}
                    onChange={setProjectModelSettings}
                    onSave={handleSaveProjectModelSettings}
                  />
                </details>
                <details className="panel project-tool-section">
                  <summary>Export</summary>
                  <div className="button-row">
                    <button type="button" onClick={handleExport}>
                      Create Full Project Export
                    </button>
                    <button type="button" onClick={handleLayer2Export}>
                      Create Layer 2 Export
                    </button>
                  </div>
                  <p className="muted">Exports are written to the configured local exports folder.</p>
                  {lastExport ? (
                    <div className="export-result" role="status">
                      <strong>{lastExport.kind} export created</strong>
                      {lastExport.markdown_path ? <span>Markdown: {lastExport.markdown_path}</span> : null}
                      <span>JSON: {lastExport.json_path}</span>
                    </div>
                  ) : null}
                  {layer2Graph.review_open ? (
                    <p className="warning">Layer 2 export includes unresolved review state. Layer 3 still requires approved features.</p>
                  ) : null}
                </details>
                <details className="panel project-tool-section">
                  <summary>Competitive intelligence</summary>
                  <CompetitiveIntelligencePanel
                    graph={layer2Graph}
                    pillars={approvedNodes(nodes, "pillar")}
                    onCompetitiveSettings={handleCompetitiveSettings}
                    onResearch={handleLayer2Research}
                    researchJobs={researchJobs}
                  />
                </details>
                <details className="panel export-diagnostics">
                  <summary>Advanced diagnostics and generation memory</summary>
                  <p className="muted">{memories.length} memory records{quarantine ? " including Layer 1 quarantine data" : ""}.</p>
                  <details>
                    <summary>Generation memory</summary>
                    <pre>{JSON.stringify(memories, null, 2)}</pre>
                  </details>
                  {quarantine ? (
                    <details>
                      <summary>Layer 1 quarantine</summary>
                      <pre>{JSON.stringify(quarantine.content, null, 2)}</pre>
                    </details>
                  ) : null}
                </details>
              </section>
            ) : null}
          </>
        ) : (
          <div className="project-loading-state">
            <strong>Project could not be opened.</strong>
            <p className="muted">{error || "The project snapshot is unavailable."}</p>
            <button type="button" onClick={() => setActiveProjectId("")}>Back To Library</button>
          </div>
        )}
      </main>

      {project ? (
        <AssistantDrawer
          open={assistantOpen}
          projectId={project.id}
          activeScope={assistantScope}
          focus={{
            active_view: activeTab,
            view_mode: workspaceState?.view_mode || "map",
            table_scope: workspaceState?.table_scope || "focused",
            entity_type: selectedWorkspaceEntity?.entity_type || "brief",
            entity_id: selectedWorkspaceEntity?.id || "layer0-root",
            label: selectedWorkspaceEntity?.title || project.name,
            layer: selectedWorkspaceEntity?.layer ?? 0,
            parent_id: selectedWorkspaceEntity?.parent_id || null,
          }}
          apiFetch={apiFetch}
          onClose={() => setAssistantOpen(false)}
          onNavigate={navigateFromAssistant}
        />
      ) : null}
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
