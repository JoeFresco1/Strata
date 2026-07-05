import { useEffect, useMemo, useState } from "react";
import ExportView from "./workspace/ExportView";
import Layer0View from "./workspace/Layer0View";
import Layer1View from "./workspace/Layer1View";
import Layer2View from "./workspace/Layer2View";
import Layer3View from "./workspace/Layer3View";
import LayerTabBar from "./workspace/LayerTabBar";
import ProgressTrack from "./workspace/ProgressTrack";
import TreeGraphView from "./workspace/TreeGraphView";
import { getLayerJobState, getLayerStatus, normalizeWorkspaceTab } from "./workspace/workspaceSelectors";
import "./workspace/workspace.css";

function workspaceTabFromState(workspaceState) {
  return normalizeWorkspaceTab(workspaceState?.map_state?.workspace_tab);
}

function jobMatches(workflowNames, scope) {
  return (job) => {
    const workflow = String(job.workflow || job.job_type || "");
    return workflowNames.some((name) => workflow.includes(name)) || (scope && job.scope === scope);
  };
}

export default function ProductTreeTab({
  activeProjectId,
  brief,
  conversation,
  handleBriefSave,
  handleGenerateLayer1,
  handleGenerateLayer2,
  handleGenerateLayer3,
  handleLayer1PillarCreate,
  handleLayer2FeatureCreate,
  handleLayer2Export,
  handleLayer2Research,
  handleLayer2Review,
  handleLayer3ExpansionReview,
  handleNodeSave,
  handleProjectArchiveExport,
  handlePlanChat,
  handlePublishBrief,
  handleRerunLayer0Research,
  handleRerunLayer1Research,
  lastExport,
  layer2Graph,
  handleExport,
  project,
  researchFindings,
  researchJobs,
  setWorkspaceState,
  snapshot,
  workspaceState,
}) {
  const [activeWorkspaceTab, setActiveWorkspaceTab] = useState(workspaceTabFromState(workspaceState));
  const layerStatus = useMemo(() => getLayerStatus(snapshot), [snapshot]);

  useEffect(() => {
    const nextTab = workspaceTabFromState(workspaceState);
    setActiveWorkspaceTab(nextTab);
  }, [activeProjectId, workspaceState?.map_state?.workspace_tab]);

  function setTab(tabId) {
    if (layerStatus[tabId]?.locked) return;
    setActiveWorkspaceTab(tabId);
    setWorkspaceState((current) => ({
      ...(current || {}),
      map_state: {
        ...((current || {}).map_state || {}),
        workspace_tab: tabId,
      },
    }));
  }

  function focusEntity(tabId, entityId) {
    setTab(tabId);
    setWorkspaceState((current) => ({
      ...(current || {}),
      selected_entity_id: entityId,
      selected_entity_type: tabId === "layer2" ? "feature" : tabId === "layer1" ? "pillar" : "brief",
      map_state: {
        ...((current || {}).map_state || {}),
        workspace_tab: tabId,
      },
    }));
    window.requestAnimationFrame(() => {
      document.getElementById(`workspace-panel-${tabId}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  const snapshotWithJobs = {
    ...(snapshot || {}),
    research_jobs: researchJobs || [],
    platform_jobs: snapshot?.platform_jobs || [],
    research_findings: researchFindings || [],
    layer2_graph: layer2Graph || {},
  };
  const layer0ResearchJob = getLayerJobState(snapshotWithJobs, jobMatches(["layer0"], "layer0"));
  const layer1GenerationJob = getLayerJobState(snapshotWithJobs, jobMatches(["layer1_generation", "generate_layer1"], "layer1"));
  const layer1ResearchJob = getLayerJobState(snapshotWithJobs, jobMatches(["layer1_pillar", "layer1"], "layer1"));
  const layer2GenerationJob = getLayerJobState(snapshotWithJobs, jobMatches(["layer2_generation", "generate_layer2"], "layer2"));
  const layer2ResearchJob = getLayerJobState(snapshotWithJobs, jobMatches(["layer2_feature", "layer2"], "layer2"));
  const layer3GenerationJob = getLayerJobState(snapshotWithJobs, jobMatches(["layer3_generation", "generate_layer3"], "layer3"));

  function renderActiveTab() {
    if (activeWorkspaceTab === "layer0") {
      return (
        <Layer0View
          brief={brief}
          conversation={conversation}
          onSave={handleBriefSave}
          onChat={handlePlanChat}
          onPublish={handlePublishBrief}
          onResearch={handleRerunLayer0Research}
          researchJobState={layer0ResearchJob}
        />
      );
    }
    if (activeWorkspaceTab === "layer1") {
      return (
        <Layer1View
          snapshot={snapshotWithJobs}
          onGenerate={handleGenerateLayer1}
          onCreatePillar={handleLayer1PillarCreate}
          onNodeSave={handleNodeSave}
          onResearch={() => handleRerunLayer1Research([])}
          generationJobState={layer1GenerationJob}
          researchJobState={layer1ResearchJob}
        />
      );
    }
    if (activeWorkspaceTab === "layer2") {
      return (
        <Layer2View
          snapshot={snapshotWithJobs}
          onGenerate={handleGenerateLayer2}
          onReview={handleLayer2Review}
          onCreateFeature={handleLayer2FeatureCreate}
          onResearch={handleLayer2Research}
          generationJobState={layer2GenerationJob}
          researchJobState={layer2ResearchJob}
        />
      );
    }
    if (activeWorkspaceTab === "layer3") {
      return (
        <Layer3View
          snapshot={snapshotWithJobs}
          onGenerate={handleGenerateLayer3}
          onReviewExpansion={handleLayer3ExpansionReview}
          generationJobState={layer3GenerationJob}
        />
      );
    }
    if (activeWorkspaceTab === "export") {
      return (
        <ExportView
          layer2Graph={layer2Graph}
          lastExport={lastExport}
          onExport={handleExport}
          onLayer2Export={handleLayer2Export}
          onProjectArchiveExport={handleProjectArchiveExport}
        />
      );
    }
    if (activeWorkspaceTab === "tree") {
      return <TreeGraphView snapshot={snapshotWithJobs} onNavigate={focusEntity} />;
    }
    return <TreeGraphView snapshot={snapshotWithJobs} onNavigate={focusEntity} />;
  }

  return (
    <section className="product-workspace-shell" aria-label={`${project?.name || "Project"} workspace`}>
      <ProgressTrack layerStatus={layerStatus} />
      <LayerTabBar activeTab={activeWorkspaceTab} layerStatus={layerStatus} onTabChange={setTab} />
      {renderActiveTab()}
    </section>
  );
}
