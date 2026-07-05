import { useEffect, useState } from "react";

export const WORKSPACE_COMPACT_BREAKPOINT = 860;
export const WORKSPACE_COMPACT_MEDIA = `(max-width: ${WORKSPACE_COMPACT_BREAKPOINT}px)`;

export const LAYER_TABS = [
  { id: "tree", label: "Tree", statusKey: "tree" },
  { id: "layer0", label: "Layer 0", statusKey: "layer0" },
  { id: "layer1", label: "Layer 1", statusKey: "layer1" },
  { id: "layer2", label: "Layer 2", statusKey: "layer2" },
  { id: "layer3", label: "Layer 3", statusKey: "layer3" },
  { id: "export", label: "Export", statusKey: "export" },
];

export const PROGRESS_STEPS = [
  { id: "idea", label: "Idea", statusKey: "layer0" },
  { id: "pillars", label: "Pillars", statusKey: "layer1" },
  { id: "features", label: "Features", statusKey: "layer2" },
  { id: "details", label: "Details", statusKey: "layer3" },
  { id: "export", label: "Export", statusKey: "export" },
];

export function useIsCompactWorkspace() {
  const [compact, setCompact] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(WORKSPACE_COMPACT_MEDIA).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const query = window.matchMedia(WORKSPACE_COMPACT_MEDIA);
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  return compact;
}

function layer2Features(snapshot) {
  return snapshot?.layer2_graph?.workbench?.rows || snapshot?.layer2_graph?.features || [];
}

function layer3Expansions(snapshot) {
  return snapshot?.layer3?.expansions || [];
}

function keptPillars(snapshot) {
  return (snapshot?.nodes || []).filter((node) => node.layer === 1 && node.node_type === "pillar" && ["kept", "prioritized"].includes(node.status));
}

function reviewedPillars(snapshot) {
  return (snapshot?.nodes || []).filter((node) => node.layer === 1 && node.node_type === "pillar" && node.status !== "generated");
}

export function approvedLayer2Features(snapshot) {
  return layer2Features(snapshot).filter((feature) => feature.status === "approved" || feature.layer3_ready);
}

export function getLayerStatus(snapshot) {
  const brief = snapshot?.brief;
  const pillars = (snapshot?.nodes || []).filter((node) => node.layer === 1 && node.node_type === "pillar");
  const kept = keptPillars(snapshot);
  const features = layer2Features(snapshot);
  const approvedFeatures = approvedLayer2Features(snapshot);
  const expansions = layer3Expansions(snapshot);
  const layer0Complete = brief?.status === "published";
  const layer1Unlocked = layer0Complete;
  const layer2Unlocked = layer1Unlocked && kept.length > 0;
  const layer3Unlocked = layer2Unlocked && approvedFeatures.length > 0;
  const allPillarsReviewed = pillars.length > 0 && reviewedPillars(snapshot).length === pillars.length;
  const allFeaturesReviewed = features.length > 0 && features.every((feature) => !["candidate", "needs_review"].includes(feature.status));

  // Future v2: once upstream edits are allowed after downstream work exists, keep unlocked layers accessible and mark downstream layers needs_review instead of relocking them.
  return {
    tree: { status: "active", locked: false, label: "Graph" },
    layer0: {
      status: layer0Complete ? "complete" : "active",
      locked: false,
      label: layer0Complete ? "Published" : "Draft",
    },
    layer1: {
      status: !layer1Unlocked ? "locked" : allPillarsReviewed ? "complete" : "active",
      locked: !layer1Unlocked,
      label: !layer1Unlocked ? "Publish Layer 0 to unlock" : allPillarsReviewed ? "Reviewed" : "Review pillars",
    },
    layer2: {
      status: !layer2Unlocked ? "locked" : allFeaturesReviewed ? "complete" : "active",
      locked: !layer2Unlocked,
      label: !layer2Unlocked ? "Keep Layer 1 pillars to unlock" : allFeaturesReviewed ? "Reviewed" : "Review features",
    },
    layer3: {
      status: !layer3Unlocked ? "locked" : expansions.length ? "active" : "needs_review",
      locked: !layer3Unlocked,
      label: !layer3Unlocked ? "Approve Layer 2 features to unlock" : expansions.length ? "Expansion ready" : "Generate details",
    },
    export: {
      status: expansions.some((item) => item.review_state === "approved") ? "active" : "locked",
      locked: !expansions.some((item) => item.review_state === "approved"),
      label: "Export",
    },
  };
}

export function normalizeWorkspaceTab(tabId) {
  if (!tabId || tabId === "map" || tabId === "overview") return "tree";
  return tabId;
}

function treeNode({ id, name, status, source, tab, entityType, children = [] }) {
  return { id, name, status, source, tab, entityType, children };
}

export function buildTreeFromSnapshot(snapshot) {
  const project = snapshot?.project || {};
  const brief = snapshot?.brief || {};
  const pillars = layer1Pillars(snapshot);
  const featuresByPillar = layer2FeaturesByPillar(snapshot);
  const expansionsByFeature = new Map();
  layer3Expansions(snapshot).forEach((expansion) => {
    const featureId = expansion.feature_id || expansion.provenance?.source_layer2_feature_id;
    if (!featureId) return;
    expansionsByFeature.set(featureId, [...(expansionsByFeature.get(featureId) || []), expansion]);
  });

  return treeNode({
    id: "layer0-root",
    name: project.name || brief.product_idea || "Project",
    status: brief.status || "draft",
    source: "layer0",
    tab: "layer0",
    entityType: "brief",
    children: pillars.map((pillar) => treeNode({
      id: pillar.id,
      name: pillar.title,
      status: pillar.status || "generated",
      source: "layer1",
      tab: "layer1",
      entityType: "pillar",
      children: (featuresByPillar.get(pillar.id) || []).map((feature) => treeNode({
        id: feature.id,
        name: feature.canonical_name,
        status: feature.status || "candidate",
        source: "layer2",
        tab: "layer2",
        entityType: "feature",
        children: (expansionsByFeature.get(feature.id) || []).map((expansion) => treeNode({
          id: expansion.id,
          name: expansion.feature_name,
          status: expansion.review_state || "draft",
          source: "layer3",
          tab: "layer3",
          entityType: "expansion",
          children: [],
        })),
      })),
    })),
  });
}

export function layer1Pillars(snapshot) {
  return (snapshot?.nodes || [])
    .filter((node) => node.layer === 1 && node.node_type === "pillar")
    .sort((left, right) => (left.priority ?? 99) - (right.priority ?? 99) || left.title.localeCompare(right.title));
}

export function layer2FeaturesByPillar(snapshot) {
  const grouped = new Map();
  layer2Features(snapshot).forEach((feature) => {
    const ownerId = feature.owner_pillar_id || "unassigned";
    grouped.set(ownerId, [...(grouped.get(ownerId) || []), feature]);
  });
  return grouped;
}

export function getLayer3Expansions(snapshot) {
  return layer3Expansions(snapshot);
}

export function getLayerJobState(snapshot, matcher) {
  const jobs = [
    ...(snapshot?.research_jobs || []).map((job) => ({ ...job, workflow: job.job_type || job.workflow || job.scope })),
    ...(snapshot?.platform_jobs || []),
  ].filter(matcher);
  const active = jobs.find((job) => ["queued", "running"].includes(job.status));
  if (active) return { state: "running", job: active, jobs };
  const failed = jobs.find((job) => ["failed", "interrupted"].includes(job.status));
  if (failed) return { state: "failed", job: failed, jobs };
  return { state: "idle", job: jobs[0] || null, jobs };
}

export function statusLabel(status) {
  return status.replaceAll("_", " ");
}
