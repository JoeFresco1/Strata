import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiFetch, subscribeApiActivity } from "./apiClient";
import { HAMBURGER_ACTIONS, applyAssistantNavigation, assistantScopeFor, findWorkspaceEntity, sortProjects } from "./appUtils";
import AppModals from "./AppModals";
import AssistantDrawer from "./AssistantDrawer";
import ProjectAnalytics from "./ProjectAnalytics";
import ProjectToolsTab from "./ProjectToolsTab";
import ProductTreeTab from "./ProductTreeTab";
import SetupWizard from "./SetupWizard";
import { useProjectLifecycle } from "./useProjectLifecycle";
import { buildWorkspaceTree } from "./projectWorkspaceData";
import { ProjectHub } from "./ProjectShell";

function parseOptionalPositiveInt(value) {
  const trimmed = String(value).trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function HeaderIcon({ kind }) {
  if (kind === "analytics") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
        <path d="M5 19V9h3v10H5Zm5.5 0V5h3v14h-3Zm5.5 0v-7h3v7h-3Z" />
      </svg>
    );
  }
  if (kind === "assistant") {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
        <path d="M12 3a7 7 0 0 0-7 7v3.8L3.7 17A1 1 0 0 0 4.6 18H9l2.2 2.2a1.1 1.1 0 0 0 1.6 0L15 18h4.4a1 1 0 0 0 .9-1.4L19 13.8V10a7 7 0 0 0-7-7Zm-3 8a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 9 11Zm6 0a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 15 11Zm-5 3h4v1.6h-4V14Z" />
      </svg>
    );
  }
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
      <path d="M19.4 13.5c.1-.5.1-1 .1-1.5s0-1-.1-1.5l2-1.5-2-3.5-2.4 1a7.8 7.8 0 0 0-2.6-1.5L14 2h-4l-.4 2.5A7.8 7.8 0 0 0 7 6L4.6 5l-2 3.5 2 1.5c-.1.5-.1 1-.1 1.5s0 1 .1 1.5l-2 1.5 2 3.5 2.4-1a7.8 7.8 0 0 0 2.6 1.5L10 22h4l.4-2.5A7.8 7.8 0 0 0 17 18l2.4 1 2-3.5-2-1.5ZM12 15.5A3.5 3.5 0 1 1 12 8a3.5 3.5 0 0 1 0 7.5Z" />
    </svg>
  );
}

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
  const [layer1TotalCap, setLayer1TotalCap] = useState(null);
  const [layer1MinNew, setLayer1MinNew] = useState(2);
  const [layer2Thinking, setLayer2Thinking] = useState(false);
  const [layer2MaxRounds, setLayer2MaxRounds] = useState(5);
  const [layer2TargetPerRound, setLayer2TargetPerRound] = useState(10);
  const [layer2TotalCap, setLayer2TotalCap] = useState(null);
  const [layer2MinNew, setLayer2MinNew] = useState(2);
  const [lastExport, setLastExport] = useState(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [setupState, setSetupState] = useState(null);
  const [projectLoading, setProjectLoading] = useState(false);
  const [pendingMutations, setPendingMutations] = useState(0);
  const savedWorkspaceStates = useRef(new Map());
  const workspaceSaveQueue = useRef(Promise.resolve());
  const {
    projectLifecycleState,
    setProjectLifecycleState,
    projectSearchQuery,
    setProjectSearchQuery,
    editingProject,
    setEditingProject,
    editProjectName,
    setEditProjectName,
    editProjectIdea,
    setEditProjectIdea,
    showImportProject,
    setShowImportProject,
    importArchivePath,
    setImportArchivePath,
    beginEditProject,
    handleEditProject,
    handleCloneProject,
    handleArchiveProject,
    handleUnarchiveProject,
    handleImportProject,
    handleProjectArchiveExport,
  } = useProjectLifecycle({
    apiFetch,
    activeProjectId,
    snapshot,
    applySnapshot,
    refreshProjects,
    setActiveProjectId,
    setActiveTab,
    setError,
    setStatusMessage,
  });
  useEffect(() => subscribeApiActivity(setPendingMutations), []);
  useEffect(() => {
    let active = true;
    async function loadBootstrap() {
      setBootstrapLoading(true);
      try {
        const [configPayload, projectsPayload, healthPayload, setupPayload] = await Promise.all([
          apiFetch("/config"),
          apiFetch(`/projects?state=${projectLifecycleState}&query=${encodeURIComponent(projectSearchQuery)}&sort=${sortOrder}`),
          apiFetch("/health"),
          apiFetch("/setup/status"),
        ]);
        if (!active) return;
        setConfig(configPayload);
        setAppSettings(configPayload);
        setProjects(projectsPayload);
        setSetupState(setupPayload);
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
    if (snapshot?.project?.lifecycle_state === "archived") return undefined;
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
  }, [activeProjectId, workspaceState, snapshot?.project?.lifecycle_state]);
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
  async function refreshProjects(next = {}) {
    const state = next.state || projectLifecycleState;
    const query = next.query ?? projectSearchQuery;
    const sort = next.sort || sortOrder;
    const payload = await apiFetch(`/projects?state=${state}&query=${encodeURIComponent(query)}&sort=${sort}`, { force: true });
    setProjects(payload);
  }
  useEffect(() => {
    if (!config) return;
    refreshProjects().catch((loadError) => setError(loadError.message));
  }, [projectLifecycleState, projectSearchQuery, sortOrder]);
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
          total_cap: layer1TotalCap,
          min_new_items_per_round: layer1MinNew,
          stale_rounds_to_stop: 2,
        }),
      });
      setLastSummary({
        stop_reason: "queued",
        total_rounds: 0,
        created_nodes: [],
        duplicate_candidates: 0,
        filtered_candidates: 0,
        thinking_enabled: layer1Thinking,
        final_coverage_summary: `Layer 1 generation queued as job ${payload.job?.id?.slice(0, 8) || ""}.`,
        round_summaries: [],
      });
      applySnapshot(payload.snapshot);
      setStatusMessage("Layer 1 generation queued.");
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
          total_cap: layer2TotalCap,
          min_new_items_per_round: layer2MinNew,
          stale_rounds_to_stop: 2,
        }),
      });
      setLastSummary({
        stop_reason: "queued",
        total_rounds: 0,
        created_nodes: [],
        duplicate_candidates: 0,
        filtered_candidates: 0,
        thinking_enabled: layer2Thinking,
        final_coverage_summary: `Layer 2 generation queued as job ${payload.job?.id?.slice(0, 8) || ""}.`,
        round_summaries: [],
      });
      applySnapshot(payload.snapshot);
      setStatusMessage("Layer 2 generation queued.");
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

  async function handleLayer1PillarCreate(payload) {
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/layer1/pillars`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      applySnapshot(response.snapshot);
      setStatusMessage("Layer 1 pillar added.");
    } catch (createError) {
      setError(createError.message);
      throw createError;
    }
  }

  async function handleLayer2FeatureUpdate(featureId, payload) {
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
    const action_type = status === "prioritized"
      ? "prioritize"
      : status === "kept"
        ? "keep"
        : status === "approved"
          ? "approve_for_layer3"
          : status;
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

  async function handleMergeFeature(featureId, targetFeatureId) {
    await apiFetch(`/projects/${activeProjectId}/layer2/review`, {
      method: "POST",
      body: JSON.stringify({
        action_type: "merge",
        feature_id: featureId,
        target_feature_id: targetFeatureId,
        payload: { rationale: "Reviewer combined this feature into the selected winner." },
      }),
    });
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

  async function handleGenerateLayer3(featureIds = []) {
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/generate/layer3`, {
        method: "POST",
        body: JSON.stringify({
          feature_ids: featureIds,
          thinking_enabled: false,
        }),
      });
      applySnapshot(response.snapshot);
      setStatusMessage("Layer 3 generation queued.");
    } catch (generationError) {
      setError(generationError.message);
      throw generationError;
    }
  }

  async function handleLayer3ExpansionReview(expansionId, action) {
    setError("");
    try {
      const response = await apiFetch(`/projects/${activeProjectId}/layer3/expansions/${expansionId}/review`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      applySnapshot(response.snapshot);
      setStatusMessage(`Layer 3 expansion marked ${action}.`);
    } catch (reviewError) {
      setError(reviewError.message);
      throw reviewError;
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
  const project = snapshot?.project || null;
  const competitiveIntelligenceEnabled = projectModelSettings?.competitive_intelligence_enabled ?? true;
  const quarantine = memories.find((item) => item.scope === "layer1" && item.memory_type === "quarantine");
  const layer1Enabled = brief?.status === "published";
  const normalizedProjectQuery = projectSearchQuery.trim().toLowerCase();
  const visibleProjects = normalizedProjectQuery
    ? projects.filter((item) => `${item.name || ""} ${item.idea || ""}`.toLowerCase().includes(normalizedProjectQuery))
    : projects;
  const sortedProjects = sortProjects(visibleProjects, sortOrder);
  const workspaceTree = useMemo(
    () => buildWorkspaceTree(project, brief, nodes, layer2Graph),
    [project, brief, nodes, layer2Graph],
  );
  const selectedWorkspaceEntity = useMemo(
    () => findWorkspaceEntity(workspaceTree, workspaceState?.selected_entity_id),
    [workspaceTree, workspaceState?.selected_entity_id],
  );
  const assistantScope = assistantScopeFor(activeTab, selectedWorkspaceEntity);
  const currentTabLabel = activeTab === "Analytics" ? "Analytics" : activeTab === "Project" ? "Project Settings" : "Product Tree";

  if (bootstrapLoading && !config) {
    return <div className="app-loading-screen"><div className="loading-spinner" /><strong>Loading Strata</strong><span>Connecting to the local workspace...</span></div>;
  }

  if (setupState && !setupState.completed) {
    return <SetupWizard defaults={setupState.defaults} apiFetch={apiFetch} onComplete={(result) => {
      setSetupState({ ...setupState, completed: true });
      setStatusMessage(result.model_ok ? "Model connected." : result.model_message);
    }} />;
  }

  if (!config) {
    return <div className="app-loading-screen"><strong>Strata could not load.</strong><span>{error || "The local API is unavailable."}</span><button type="button" onClick={() => window.location.reload()}>Retry</button></div>;
  }

  function navigateFromAssistant(layer, citation = {}) {
    applyAssistantNavigation({ layer, citation, setActiveTab, setWorkspaceState });
  }
  const assistantBubbleHidden = Boolean(workspaceState?.map_state?.layout?.assistant_bubble_hidden);
  function setAssistantBubbleHidden(hidden) {
    setWorkspaceState((current) => ({
      ...(current || {}),
      map_state: {
        ...((current || {}).map_state || {}),
        layout: {
          ...(((current || {}).map_state || {}).layout || {}),
          assistant_bubble_hidden: hidden,
        },
      },
    }));
  }
  const modalState = { appSettings, config, editProjectIdea, editProjectName, editingProject, importArchivePath, modelSettingsSaveState, newProjectIdea, newProjectName, showCreateProject, showGuide, showImportProject, showPrompts, showSettings };
  const modalActions = { handleCreateProject, handleEditProject, handleImportProject, handleSaveModelSettings, setAppSettings, setEditProjectIdea, setEditProjectName, setEditingProject, setImportArchivePath, setNewProjectIdea, setNewProjectName, setShowCreateProject, setShowGuide, setShowImportProject, setShowPrompts, setShowSettings };

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
              {HAMBURGER_ACTIONS.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  className="rail-action"
                  onClick={() => {
                    if (action.id === "guide") setShowGuide(true);
                    if (action.id === "prompts") setShowPrompts(true);
                    if (action.id === "settings") setShowSettings(true);
                  }}
                >
                  <span className="rail-action-label">{action.label}</span>
                </button>
              ))}
            </div>
            <div className="nav-rail-footer">
              <div className="rail-runtime-card">
                <span className="rail-runtime-kicker">Local runtime</span>
                <strong>{statusMessage}</strong>
                <div className="rail-runtime-meta muted">
                  <span>API {API_BASE}</span>
                  <span>DB {config.database_backend}</span>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </aside>

      <main className="main-content">
        {project ? (
          <div className="page-header">
            <div className="project-header-main">
              <button
                type="button"
                className="secondary-button project-header-back-button"
                onClick={() => setActiveProjectId("")}
              >
                Back to library
              </button>
              <h2>{project.name}</h2>
              <p>{project.idea}</p>
              <div className="project-header-meta" aria-label="Project state">
                <span className={`status-pill ${project.lifecycle_state || "active"}`}>{project.lifecycle_state || "active"}</span>
                <span className={`status-pill ${brief?.status || "draft"}`}>Brief {brief?.status || "draft"}</span>
                <span className="status-pill">Tab {currentTabLabel}</span>
              </div>
            </div>
            <div className="project-header-actions">
              <button
                type="button"
                className={activeTab === "Workspace" ? "secondary-button project-content-button active" : "secondary-button project-content-button"}
                onClick={() => setActiveTab("Workspace")}
              >
                Product Tree
              </button>
              <button
                type="button"
                className={activeTab === "Analytics" ? "icon-button project-header-icon active" : "icon-button project-header-icon"}
                onClick={() => setActiveTab("Analytics")}
                aria-label="Open runtime analytics"
                title="Runtime Analytics"
              >
                <HeaderIcon kind="analytics" />
              </button>
              <button
                type="button"
                className={activeTab === "Project" ? "icon-button project-header-icon active" : "icon-button project-header-icon"}
                onClick={() => setActiveTab("Project")}
                aria-label="Open project settings"
                title="Project Settings"
              >
                <HeaderIcon kind="settings" />
              </button>
              <button
                type="button"
                className="icon-button project-header-icon assistant-open-button"
                onClick={() => setAssistantOpen(true)}
                aria-label="Open assistant"
                title="Assistant"
              >
                <HeaderIcon kind="assistant" />
              </button>
            </div>
            {error ? <div className="error-banner">{error}</div> : null}
          </div>
        ) : error ? <div className="error-banner">{error}</div> : null}
        {project?.lifecycle_state === "archived" ? (
          <div className="status-banner">
            <strong>Archived project.</strong> This project is read-only until it is unarchived.
            <div className="button-row compact">
              <button type="button" onClick={() => handleUnarchiveProject(project)}>Unarchive</button>
              <button type="button" className="secondary-button" onClick={handleProjectArchiveExport}>Export Archive</button>
            </div>
          </div>
        ) : null}
        {!activeProjectId ? (
          <ProjectHub
            projects={sortedProjects}
            loading={bootstrapLoading}
            sortOrder={sortOrder}
            onSortOrderChange={setSortOrder}
            lifecycleState={projectLifecycleState}
            onLifecycleStateChange={setProjectLifecycleState}
            searchQuery={projectSearchQuery}
            onSearchQueryChange={setProjectSearchQuery}
            onCreateProject={() => setShowCreateProject(true)}
            onOpenProject={(projectId) => {
              setActiveTab("Workspace");
              setActiveProjectId(projectId);
            }}
            onEditProject={beginEditProject}
            onCloneProject={handleCloneProject}
            onArchiveProject={handleArchiveProject}
            onUnarchiveProject={handleUnarchiveProject}
            onImportProject={() => setShowImportProject(true)}
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
            <section className="tab-content">
              {activeTab === "Analytics" ? (
                <ProjectAnalytics projectId={activeProjectId} apiFetch={apiFetch} />
              ) : activeTab === "Project" ? (
                <ProjectToolsTab
                  config={config}
                  competitiveIntelligenceEnabled={competitiveIntelligenceEnabled}
                  layer2Graph={layer2Graph}
                  lastExport={lastExport}
                  memories={memories}
                  nodes={nodes}
                  projectModelSettings={projectModelSettings}
                  projectSettingsSaveState={projectSettingsSaveState}
                  quarantine={quarantine}
                  researchJobs={researchJobs}
                  onCompetitiveSettings={handleCompetitiveSettings}
                  onExport={handleExport}
                  onLayer2Export={handleLayer2Export}
                  onProjectSettingsChange={setProjectModelSettings}
                  onProjectSettingsSave={handleSaveProjectModelSettings}
                  onResearchLayer2={handleLayer2Research}
                  onProjectArchiveExport={handleProjectArchiveExport}
                />
              ) : (
                <ProductTreeTab
                  activeProjectId={activeProjectId}
                  brief={brief}
                  conversation={conversation}
                  handleBriefSave={handleBriefSave}
                  handleExport={handleExport}
                  handleGenerateLayer1={handleGenerateLayer1}
                  handleGenerateLayer2={handleGenerateLayer2}
                  handleGenerateLayer3={handleGenerateLayer3}
                  handleLayer1PillarCreate={handleLayer1PillarCreate}
                  handleLayer2Export={handleLayer2Export}
                  handleLayer2FeatureCreate={handleLayer2FeatureCreate}
                  handleLayer2Research={handleLayer2Research}
                  handleLayer2Review={handleLayer2Review}
                  handleLayer3ExpansionReview={handleLayer3ExpansionReview}
                  handleNodeSave={handleNodeSave}
                  handleProjectArchiveExport={handleProjectArchiveExport}
                  handlePlanChat={handlePlanChat}
                  handlePublishBrief={handlePublishBrief}
                  handleRerunLayer0Research={handleRerunLayer0Research}
                  handleRerunLayer1Research={handleRerunLayer1Research}
                  lastExport={lastExport}
                  layer2Graph={layer2Graph}
                  project={project}
                  researchFindings={researchFindings}
                  researchJobs={researchJobs}
                  setWorkspaceState={setWorkspaceState}
                  snapshot={snapshot}
                  workspaceState={workspaceState}
                />
              )}
            </section>
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
        !assistantBubbleHidden ? (
          <button
            type="button"
            className="floating-assistant-button"
            onClick={() => setAssistantOpen(true)}
            onContextMenu={(event) => {
              event.preventDefault();
              setAssistantBubbleHidden(true);
            }}
            aria-label="Open assistant"
            title="Open assistant. Right-click to hide."
          >
            <HeaderIcon kind="assistant" />
          </button>
        ) : null
      ) : null}
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
      <AppModals {...modalState} {...modalActions} />
    </div>
  );
}
