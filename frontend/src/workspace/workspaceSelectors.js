import { useEffect, useState } from "react";

export const WORKSPACE_COMPACT_BREAKPOINT = 860;
export const WORKSPACE_COMPACT_MEDIA = `(max-width: ${WORKSPACE_COMPACT_BREAKPOINT}px)`;

export const LAYER_TABS = [
  { id: "map", label: "Map", badge: "", statusKey: "map" },
  { id: "layer0", label: "Product Idea", badge: "L0", statusKey: "layer0" },
  { id: "layer1", label: "Pillars", badge: "L1", statusKey: "layer1" },
  { id: "layer2", label: "Features", badge: "L2", statusKey: "layer2" },
  { id: "layer3", label: "Sub-features", badge: "L3", statusKey: "layer3" },
  { id: "export", label: "Export", badge: "", statusKey: "export" },
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
  const expansions = snapshot?.layer3?.expansions || [];
  const approvedExpansions = expansions.filter((expansion) => expansion.review_state === "approved");
  const layer0Complete = brief?.status === "published";
  const layer1Unlocked = layer0Complete;
  const layer2Unlocked = layer1Unlocked && kept.length > 0;
  const layer3Unlocked = layer2Unlocked && approvedFeatures.length > 0;
  const allPillarsReviewed = pillars.length > 0 && reviewedPillars(snapshot).length === pillars.length;
  const allFeaturesReviewed = features.length > 0 && features.every((feature) => !["candidate", "needs_review"].includes(feature.status));
  const allApprovedFeaturesExpanded = approvedFeatures.length > 0 && approvedFeatures.every((feature) => (
    expansions.some((expansion) => expansion.feature_id === feature.id && expansion.review_state !== "rejected")
  ));

  // Future v2: once upstream edits are allowed after downstream work exists, keep unlocked layers accessible and mark downstream layers needs_review instead of relocking them.
  return {
    map: { status: "active", locked: false, label: "Map" },
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
      status: !layer3Unlocked ? "locked" : allApprovedFeaturesExpanded ? "active" : "needs_review",
      locked: !layer3Unlocked,
      label: !layer3Unlocked ? "Approve Layer 2 features to unlock" : allApprovedFeaturesExpanded ? "Feature expansions ready" : "Generate expansions",
    },
    export: {
      status: !layer2Unlocked ? "locked" : approvedExpansions.length ? "active" : "needs_review",
      locked: !layer2Unlocked,
      label: !layer2Unlocked ? "Review earlier layers first" : approvedExpansions.length ? "Layer 3 ready" : approvedFeatures.length ? "Approve expansions for Layer 3 handoff" : "Approve features first",
    },
  };
}

export function normalizeWorkspaceTab(tabId) {
  if (!tabId || tabId === "tree" || tabId === "map" || tabId === "overview") return "map";
  return tabId;
}

function scoreNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(100, number)) : null;
}

function firstScore(...values) {
  for (const value of values) {
    const score = scoreNumber(value);
    if (score !== null) return score;
  }
  return null;
}

function pillarScores(pillar) {
  const payload = pillar.json_payload || {};
  const assessment = payload.pillar_assessment || {};
  const profile = payload.implementation_profile || {};
  return {
    strategic: firstScore(assessment.strategic_value_score, payload.strategic_value_score, profile.indexed_score),
    pillarFit: firstScore(assessment.pillar_quality_score, payload.pillar_quality_score),
    distinctiveness: firstScore(assessment.distinctiveness_score, payload.distinctiveness_score),
    competitorCoverage: firstScore(profile.indexed_score, payload.competitor_coverage_score),
    implementationLeakage: firstScore(profile.indexed_score),
  };
}

function featureScores(feature) {
  return {
    strategic: scoreNumber(feature.strategic_value_score),
    pillarFit: scoreNumber(feature.pillar_fit_score),
    distinctiveness: scoreNumber(feature.distinctiveness_score),
    competitorCoverage: scoreNumber(feature.competitor_coverage_score),
    implementationLeakage: scoreNumber(feature.implementation_leakage_score),
  };
}

function firstText(...values) {
  return values.find((value) => typeof value === "string" && value.trim()) || "";
}

function firstValue(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== "") || null;
}

function treeNode({
  id,
  name,
  status,
  source,
  tab,
  entityType,
  pillarId = "",
  pillarName = "",
  layer = 0,
  layerLabel = "",
  parentId = "",
  parentName = "",
  parentTab = "",
  breadcrumb = [],
  description = "",
  reviewInfo = "",
  updatedAt = null,
  featureId = "",
  scores = {},
  searchParts = [],
  children = [],
}) {
  const resolvedBreadcrumb = breadcrumb.length ? breadcrumb : [name].filter(Boolean);
  const searchText = [
    name,
    status,
    source,
    tab,
    entityType,
    layerLabel,
    pillarName,
    parentName,
    description,
    reviewInfo,
    ...resolvedBreadcrumb,
    ...searchParts,
  ].filter(Boolean).join(" ").toLowerCase();
  return {
    id,
    name,
    status,
    source,
    tab,
    entityType,
    pillarId,
    pillarName,
    layer,
    layerLabel: layerLabel || `L${layer}`,
    parentId,
    parentName,
    parentTab,
    breadcrumb: resolvedBreadcrumb,
    description,
    reviewInfo,
    updatedAt,
    featureId,
    scores,
    searchText,
    children,
  };
}

export function buildTreeFromSnapshot(snapshot) {
  const project = snapshot?.project || {};
  const brief = snapshot?.brief || {};
  const pillars = layer1Pillars(snapshot);
  const featuresByPillar = layer2FeaturesByPillar(snapshot);
  const expansionsByFeatureId = new Map();
  (snapshot?.layer3?.expansions || []).forEach((expansion) => {
    expansionsByFeatureId.set(expansion.feature_id, expansion);
  });
  return treeNode({
    id: "layer0-root",
    name: project.name || brief.product_idea || "Project",
    status: brief.status || "draft",
    source: "layer0",
    tab: "layer0",
    entityType: "brief",
    pillarId: "",
    layer: 0,
    layerLabel: "L0",
    parentId: "",
    parentName: "",
    parentTab: "",
    breadcrumb: [project.name || brief.product_idea || "Project"],
    description: firstText(brief.product_idea, brief.goals, brief.target_users, project.description),
    reviewInfo: firstText(brief.research_summary, brief.competitive_summary),
    updatedAt: firstValue(brief.updated_at, project.updated_at, project.created_at),
    scores: {},
    searchParts: [brief.product_idea, brief.target_users, brief.goals],
    children: pillars.map((pillar) => treeNode({
      id: pillar.id,
      name: pillar.title,
      status: pillar.status || "generated",
      source: "layer1",
      tab: "layer1",
      entityType: "pillar",
      pillarId: pillar.id,
      pillarName: pillar.title,
      layer: 1,
      layerLabel: "L1",
      parentId: "layer0-root",
      parentName: project.name || brief.product_idea || "Project",
      parentTab: "layer0",
      breadcrumb: [project.name || brief.product_idea || "Project", pillar.title],
      description: firstText(pillar.description, pillar.source, pillar.json_payload?.summary),
      reviewInfo: firstText(pillar.review_note, pillar.json_payload?.review_note, pillar.json_payload?.pillar_assessment?.rationale),
      updatedAt: firstValue(pillar.updated_at, pillar.created_at),
      scores: pillarScores(pillar),
      searchParts: [pillar.description, pillar.source, pillar.json_payload?.canonical_family],
      children: (featuresByPillar.get(pillar.id) || []).map((feature) => treeNode({
        id: feature.id,
        name: feature.canonical_name,
        status: feature.status || "candidate",
        source: "layer2",
        tab: "layer2",
        entityType: "feature",
        pillarId: pillar.id,
        pillarName: pillar.title,
        layer: 2,
        layerLabel: "L2",
        parentId: pillar.id,
        parentName: pillar.title,
        parentTab: "layer1",
        breadcrumb: [project.name || brief.product_idea || "Project", pillar.title, feature.canonical_name],
        description: firstText(feature.description, feature.job_story, feature.user_problem, feature.rationale),
        reviewInfo: firstText(feature.review_note, feature.research_summary, feature.evidence_summary),
        updatedAt: firstValue(feature.updated_at, feature.created_at, feature.generated_at),
        featureId: feature.id,
        scores: featureScores(feature),
        searchParts: [feature.description, feature.feature_type, feature.granularity_class, pillar.title],
        children: expansionsByFeatureId.has(feature.id) ? [treeNode({
          id: expansionsByFeatureId.get(feature.id).id,
          name: expansionsByFeatureId.get(feature.id).title || `${feature.canonical_name} expansion`,
          status: expansionsByFeatureId.get(feature.id).review_state || "draft",
          source: "layer3",
          tab: "layer3",
          entityType: "expansion",
          pillarId: pillar.id,
          pillarName: pillar.title,
          layer: 3,
          layerLabel: "L3",
          parentId: feature.id,
          parentName: feature.canonical_name,
          parentTab: "layer2",
          breadcrumb: [project.name || brief.product_idea || "Project", pillar.title, feature.canonical_name, expansionsByFeatureId.get(feature.id).title || "Expansion"],
          description: firstText(
            expansionsByFeatureId.get(feature.id).narrative,
            expansionsByFeatureId.get(feature.id).description,
            expansionsByFeatureId.get(feature.id).intent,
            expansionsByFeatureId.get(feature.id).summary,
          ),
          reviewInfo: firstText(expansionsByFeatureId.get(feature.id).review_note, expansionsByFeatureId.get(feature.id).decision_note),
          updatedAt: firstValue(expansionsByFeatureId.get(feature.id).updated_at, expansionsByFeatureId.get(feature.id).created_at),
          featureId: feature.id,
          scores: {},
          searchParts: [feature.canonical_name, pillar.title],
          children: [],
        })] : [],
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

export function getLayerJobState(snapshot, matcher) {
  const jobs = [
    ...(snapshot?.platform_jobs || []),
    ...(snapshot?.research_jobs || []).map((job) => ({ ...job, workflow: job.job_type || job.workflow || job.scope })),
  ].filter(matcher);
  const active = jobs.find((job) => ["queued", "running"].includes(job.status));
  if (active) return { state: "running", job: active, jobs };
  const failed = jobs.find((job) => ["failed", "interrupted"].includes(job.status));
  if (failed) return { state: "failed", job: failed, jobs };
  return { state: "idle", job: jobs[0] || null, jobs };
}

export function statusLabel(status) {
  const labels = {
    active: "Draft",
    approved: "Approved",
    candidate: "Generated",
    complete: "Approved",
    cut: "Rejected",
    draft: "Draft",
    exclude: "Rejected",
    generated: "Generated",
    include: "Kept",
    kept: "Kept",
    locked: "Needs review",
    merged: "Kept",
    needs_review: "Needs review",
    not_generated: "Draft",
    prioritized: "Kept",
    published: "Published",
    rejected: "Rejected",
    reviewed: "Approved",
    undecided: "Needs review",
  };
  const key = String(status || "draft").toLowerCase();
  return labels[key] || key.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
}
