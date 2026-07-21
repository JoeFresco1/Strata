import { useEffect, useMemo, useState } from "react";
import { Layer2FeatureForm } from "../Layer2FeatureWorkbenchParts";
import ColumnHeader from "./ColumnHeader";
import { layer1Pillars, statusLabel } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceFilterField, WorkspaceStatusBadge } from "./WorkspacePage";
import WorkspaceJobNotice from "./WorkspaceJobNotice";

const UNASSIGNED_PILLAR_ID = "unassigned";
const REVIEWABLE_STATUSES = ["candidate", "needs_review"];
const ASSIGNABLE_STATUSES = ["candidate", "kept", "needs_review", "approved", "cut", "merged", "renamed"];

function relationLabel(value) {
  return String(value || "").replaceAll("_", " ");
}

function featureWarnings(feature, graph, overlapVerdicts) {
  const relationships = graph?.relationships || [];
  const relationshipWarnings = relationships.filter((relationship) => (
    relationship.source_feature_id === feature.id || relationship.target_feature_id === feature.id
  ) && ["overlaps_with", "duplicate_of", "conflicts_with"].includes(relationship.relationship_type)).map((relationship) => ({
    source: relationship.rationale?.includes("Generated candidate resembles") ? "candidate overlap" : "graph critic",
    label: relationship.relationship_type,
    detail: relationship.rationale || relationship.reason || relationship.relationship_type,
  }));
  const overlapWarnings = (overlapVerdicts || []).filter((verdict) => (
    verdict.target_id === feature.id || verdict.neighbor_id === feature.id
  ) && verdict.relation !== "distinct").map((verdict) => ({
    source: "overlap critic",
    label: verdict.relation,
    detail: verdict.rationale,
  }));
  const byKey = new Map();
  [...relationshipWarnings, ...overlapWarnings].forEach((warning) => {
    const key = `${warning.source}:${warning.label}:${warning.detail}`;
    if (!byKey.has(key)) byKey.set(key, warning);
  });
  return Array.from(byKey.values());
}

function score(value) {
  return Number(value || 0);
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function featureName(feature) {
  return feature?.canonical_name || feature?.title || feature?.name || "Untitled feature";
}

function formatScore(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "-";
  return `${value}${suffix}`;
}

function compareValues(left, right, direction) {
  const leftMissing = left === null || left === undefined || left === "";
  const rightMissing = right === null || right === undefined || right === "";
  if (leftMissing && rightMissing) return 0;
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  const result = typeof left === "number" && typeof right === "number"
    ? left - right
    : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
  return direction === "asc" ? result : -result;
}

function isApproved(feature) {
  return feature?.status === "approved" || Boolean(feature?.layer3_ready);
}

function isNeedsReview(feature) {
  return REVIEWABLE_STATUSES.includes(feature?.status);
}

function featurePillarId(feature, pillarById) {
  return feature?.owner_pillar_id && pillarById[feature.owner_pillar_id] ? feature.owner_pillar_id : UNASSIGNED_PILLAR_ID;
}

function subfeatureCount(feature, expansionByFeatureId) {
  const expansion = expansionByFeatureId[feature.id];
  if (!expansion) return 0;
  return safeArray(expansion.expansion_groups).reduce((total, group) => total + safeArray(group.options).length, 0);
}

function uniqueFeaturePillarIds(features, pillarById) {
  return Array.from(new Set(features.map((feature) => featurePillarId(feature, pillarById)).filter((id) => id !== UNASSIGNED_PILLAR_ID)));
}

function FeatureWarning({ feature, warnings, unassigned }) {
  if (!unassigned && !warnings.length) return null;
  return (
    <span className="layer2-warning-row">
      {unassigned ? <span className="layer2-unassigned-badge">Unassigned</span> : null}
      {warnings.length ? (
        <span className="warning-icon" title={warnings[0].detail} aria-label={`Warning for ${featureName(feature)}`}>!</span>
      ) : null}
    </span>
  );
}

function PillarSelector({ pillars, selectedPillarIds, onToggle }) {
  return (
    <div className="layer2-pillar-picker" aria-label="Select pillars">
      {pillars.map((pillar) => (
        <label key={pillar.id}>
          <input
            type="checkbox"
            checked={selectedPillarIds.includes(pillar.id)}
            onChange={() => onToggle(pillar.id)}
          />
          <span>{pillar.title}</span>
        </label>
      ))}
    </div>
  );
}

function DetailDrawer({
  feature,
  pillars,
  pillarById,
  graph,
  overlapVerdicts,
  onClose,
  onUpdateFeature,
}) {
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const warnings = feature ? featureWarnings(feature, graph, overlapVerdicts) : [];
  const unassigned = feature ? featurePillarId(feature, pillarById) === UNASSIGNED_PILLAR_ID : false;

  useEffect(() => {
    if (!feature) {
      setDraft(null);
      return;
    }
    setDraft({
      canonical_name: feature.canonical_name || "",
      description: feature.description || "",
      owner_pillar_id: feature.owner_pillar_id && pillarById[feature.owner_pillar_id] ? feature.owner_pillar_id : "",
      status: feature.status || "candidate",
      priority: feature.priority || "",
      notes: feature.notes || "",
    });
  }, [feature, pillarById]);

  if (!feature || !draft) return null;

  async function save() {
    setSaving(true);
    try {
      await onUpdateFeature?.(feature.id, draft);
    } finally {
      setSaving(false);
    }
  }

  return (
    <aside className="layer2-detail-drawer panel" aria-label={`${featureName(feature)} details`}>
      <div className="workspace-section-heading">
        <div>
          <span className="workspace-card-label">Feature details</span>
          <h4>{featureName(feature)}</h4>
          {unassigned ? <p className="warning">This feature is unassigned. Choose a pillar before approving or expanding it.</p> : null}
        </div>
        <button type="button" className="secondary-button" onClick={onClose}>Close</button>
      </div>
      <div className="layer2-detail-form">
        <label>
          Feature
          <input value={draft.canonical_name} onChange={(event) => setDraft({ ...draft, canonical_name: event.target.value })} />
        </label>
        <label className="layer2-detail-span">
          Description
          <textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={4} />
        </label>
        <label className={unassigned ? "layer2-assignment-warning" : ""}>
          Pillar
          <select value={draft.owner_pillar_id} onChange={(event) => setDraft({ ...draft, owner_pillar_id: event.target.value })}>
            <option value="">Assign to pillar</option>
            {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
          </select>
        </label>
        <label>
          Status
          <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
            {ASSIGNABLE_STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
          </select>
        </label>
        <label>
          Priority
          <input value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })} placeholder="high, medium, low" />
        </label>
        <label className="layer2-detail-span">
          Notes
          <textarea value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} rows={3} />
        </label>
      </div>
      {warnings.length ? (
        <div className="layer2-warning-list">
          <strong>Critic warnings</strong>
          {warnings.map((warning) => (
            <p key={`${warning.source}-${warning.label}-${warning.detail}`} className="muted">
              {warning.source}: {relationLabel(warning.label)} - {warning.detail}
            </p>
          ))}
        </div>
      ) : null}
      <div className="button-row">
        <button type="button" onClick={save} disabled={saving || !draft.canonical_name.trim() || !draft.description.trim() || !draft.owner_pillar_id}>
          {saving ? "Saving..." : "Save details"}
        </button>
      </div>
    </aside>
  );
}

export default function Layer2View({
  snapshot,
  onGenerate,
  onGenerateLayer3,
  onReview,
  onCreateFeature,
  onUpdateFeature,
  onOverlapCritic,
  onResolveOverlap,
  onResearch,
  generationJobState,
  researchJobState,
  overlapJobState,
  onCancelJob,
}) {
  const pillars = layer1Pillars(snapshot).filter((pillar) => ["kept", "prioritized"].includes(pillar.status));
  const graph = snapshot?.layer2_graph || {};
  const allFeatures = safeArray(graph?.workbench?.rows || graph?.features);
  const expansions = safeArray(snapshot?.layer3?.expansions);
  const expansionByFeatureId = useMemo(() => Object.fromEntries(expansions.map((expansion) => [expansion.feature_id, expansion])), [expansions]);
  const pillarById = useMemo(() => Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar])), [pillars]);
  const conflictCount = (graph.relationships || []).filter((relationship) => ["overlaps_with", "duplicate_of", "conflicts_with"].includes(relationship.relationship_type)).length;
  const [selectedIds, setSelectedIds] = useState([]);
  const [selectedPillarIds, setSelectedPillarIds] = useState([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ pillar: "all", status: "all" });
  const [sortConfig, setSortConfig] = useState({ key: "pillar", direction: "asc" });
  const [viewMode, setViewMode] = useState("grouped");
  const [collapsedGroups, setCollapsedGroups] = useState([]);
  const [activeFeatureId, setActiveFeatureId] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewFilter, setReviewFilter] = useState("unresolved");
  const generationRunning = generationJobState?.state === "running";
  const researchRunning = researchJobState?.state === "running";
  const overlapRunning = overlapJobState?.state === "running";
  const overlapVerdicts = snapshot?.overlap?.layer2?.verdicts || [];
  const overlapConflictCount = overlapVerdicts.filter((verdict) => verdict.relation !== "distinct").length;
  const featureById = useMemo(() => Object.fromEntries(allFeatures.map((feature) => [feature.id, feature])), [allFeatures]);
  const activeFeature = featureById[activeFeatureId] || null;
  const selectedFeatures = selectedIds.map((id) => featureById[id]).filter(Boolean);
  const selectedRowPillarIds = uniqueFeaturePillarIds(selectedFeatures, pillarById);
  const selectedPillarFeatureIds = allFeatures
    .filter((feature) => selectedPillarIds.includes(featurePillarId(feature, pillarById)))
    .map((feature) => feature.id);

  const reviewVerdicts = useMemo(() => (
    overlapVerdicts.filter((verdict) => {
      if (verdict.relation === "distinct") return false;
      if (reviewFilter === "all") return true;
      return (verdict.resolution_state || "unresolved") === reviewFilter;
    })
  ), [overlapVerdicts, reviewFilter]);

  const visibleFeatures = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = allFeatures.filter((feature) => {
      const resolvedPillarId = featurePillarId(feature, pillarById);
      const text = [featureName(feature), feature.description, feature.feature_type, feature.granularity_class, feature.status, feature.priority, pillarById[feature.owner_pillar_id]?.title, resolvedPillarId === UNASSIGNED_PILLAR_ID ? "unassigned" : ""]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return (
        (!normalizedQuery || text.includes(normalizedQuery)) &&
        (filters.pillar === "all" || resolvedPillarId === filters.pillar) &&
        (filters.status === "all" || feature.status === filters.status)
      );
    });
    return [...filtered].sort((left, right) => {
      const selectors = {
        pillar: (feature) => pillarById[feature.owner_pillar_id]?.title || "Unassigned",
        priority: (feature) => feature.priority || "",
        fit: (feature) => score(feature.pillar_fit_score),
        strategic: (feature) => score(feature.strategic_value_score),
        research: (feature) => score(feature.competitor_coverage_score),
      };
      const select = selectors[sortConfig.key] || selectors.pillar;
      return compareValues(select(left), select(right), sortConfig.direction) || featureName(left).localeCompare(featureName(right));
    });
  }, [allFeatures, filters, pillarById, query, sortConfig]);

  const groupedFeatures = useMemo(() => {
    const groups = new Map();
    visibleFeatures.forEach((feature) => {
      const id = featurePillarId(feature, pillarById);
      if (!groups.has(id)) {
        groups.set(id, {
          id,
          title: id === UNASSIGNED_PILLAR_ID ? "Unassigned" : pillarById[id]?.title || "Unassigned",
          features: [],
        });
      }
      groups.get(id).features.push(feature);
    });
    return Array.from(groups.values()).sort((left, right) => {
      if (left.id === UNASSIGNED_PILLAR_ID) return 1;
      if (right.id === UNASSIGNED_PILLAR_ID) return -1;
      return left.title.localeCompare(right.title);
    });
  }, [pillarById, visibleFeatures]);

  function toggleFeature(id) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function togglePillar(id) {
    setSelectedPillarIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleVisibleFeatures() {
    const visibleIds = visibleFeatures.map((feature) => feature.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
    setSelectedIds((current) => allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : Array.from(new Set([...current, ...visibleIds])));
  }

  function toggleGroup(groupId) {
    setCollapsedGroups((current) => current.includes(groupId) ? current.filter((id) => id !== groupId) : [...current, groupId]);
  }

  function toggleSort(key) {
    setSortConfig((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }

  async function reviewSelected(actionType) {
    const targets = selectedIds.filter((id) => allFeatures.some((feature) => feature.id === id));
    await Promise.all(targets.map((id) => onReview({ action_type: actionType, feature_id: id })));
    setSelectedIds((current) => current.filter((id) => !targets.includes(id)));
  }

  async function resolveVerdict(verdict, action) {
    await onResolveOverlap?.(verdict.id, { action });
  }

  function researchPillar(pillarId) {
    const featureIds = allFeatures.filter((feature) => featurePillarId(feature, pillarById) === pillarId).map((feature) => feature.id);
    return onResearch?.(featureIds);
  }

  function renderFeatureRow(feature) {
    const warnings = featureWarnings(feature, graph, overlapVerdicts);
    const resolvedPillarId = featurePillarId(feature, pillarById);
    const unassigned = resolvedPillarId === UNASSIGNED_PILLAR_ID;
    const approved = isApproved(feature);
    return (
      <tr key={feature.id}>
        <td><input type="checkbox" checked={selectedIds.includes(feature.id)} onChange={() => toggleFeature(feature.id)} aria-label={`Select ${featureName(feature)}`} /></td>
        <td>
          <strong>{featureName(feature)}</strong>
          <FeatureWarning feature={feature} warnings={warnings} unassigned={unassigned} />
          {warnings.length ? <p className="muted critic-source-line">{warnings.map((item) => `${item.source}: ${relationLabel(item.label)}`).join(" | ")}</p> : null}
        </td>
        <td><p className="muted layer2-description-cell">{feature.description || "No description yet."}</p></td>
        <td>{unassigned ? <span className="layer2-unassigned-badge">Unassigned</span> : pillarById[feature.owner_pillar_id]?.title}</td>
        <td><WorkspaceStatusBadge status={feature.status} /></td>
        <td>{formatScore(feature.pillar_fit_score)}</td>
        <td>{formatScore(feature.strategic_value_score)}</td>
        <td>{formatScore(feature.competitor_coverage_score, "%")}</td>
        <td>{subfeatureCount(feature, expansionByFeatureId) || "-"}</td>
        <td>
          <div className="layer2-feature-actions">
            <button type="button" className="secondary-button" onClick={() => setActiveFeatureId(feature.id)}>Open details</button>
            <button type="button" className="secondary-button" onClick={() => onGenerate([feature.owner_pillar_id])} disabled={generationRunning || unassigned} title={unassigned ? "Assign a pillar before generating more features for this row." : "Generate more features for this row's pillar."}>Generate more</button>
            <button type="button" className="secondary-button" onClick={() => onGenerateLayer3?.([feature.id])} disabled={!approved} title={!approved ? "Approve this feature before generating sub-features." : "Generate sub-features"}>Generate sub-features</button>
            <button type="button" className="secondary-button" onClick={() => onResearch?.([feature.id])} disabled={researchRunning} title={researchRunning ? "Layer 2 research is already running." : "Research this row"}>Research</button>
            <button type="button" className="secondary-button" onClick={() => onReview({ action_type: "approve_for_layer3", feature_id: feature.id })}>Approve</button>
            <button type="button" className="secondary-button danger-button" onClick={() => onReview({ action_type: "cut", feature_id: feature.id })}>Reject</button>
          </div>
        </td>
      </tr>
    );
  }

  function renderFeatureTable(features, label = "Layer 2 features") {
    return (
      <div className="workspace-table-wrap workspace-table-panel layer2-table-wrap">
        <table className="workspace-review-table layer2-review-table" aria-label={label}>
          <thead>
            <tr>
              <th scope="col"><ColumnHeader label="Checkbox" description="Choose one or more features for bulk review, generation, or research actions." /></th>
              <th scope="col"><ColumnHeader label="Feature" description="The Layer 2 capability candidate." /></th>
              <th scope="col"><ColumnHeader label="Description" description="The feature description or job story." /></th>
              <th scope="col"><ColumnHeader label="Pillar" description="The Layer 1 pillar that currently owns this feature." sortKey="pillar" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
              <th scope="col"><ColumnHeader label="Status" description="Current review state, such as generated, kept, approved, or rejected." /></th>
              <th scope="col"><ColumnHeader label="Fit score" description="How strongly this feature belongs under its assigned pillar." sortKey="fit" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
              <th scope="col"><ColumnHeader label="Strategic score" description="Estimated product value or planning importance for this feature." sortKey="strategic" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
              <th scope="col"><ColumnHeader label="Research score" description="Competitor coverage score from feature-level competitive research." sortKey="research" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
              <th scope="col"><ColumnHeader label="Sub-feature count" description="Generated Layer 3 sub-feature/options count." /></th>
              <th scope="col"><ColumnHeader label="Actions" description="Row-level controls to open details, generate sub-features, research, approve, or reject." /></th>
            </tr>
          </thead>
          <tbody>{features.map(renderFeatureRow)}</tbody>
        </table>
      </div>
    );
  }

  return (
    <WorkspacePageLayout
      id="workspace-panel-layer2"
      className="layer2-workspace-page"
      ariaLabel="Layer 2 features"
      title="L2 Features"
      description="Create and approve features under each product pillar before expanding them into sub-features."
      status={!allFeatures.length ? "draft" : allFeatures.every((feature) => !REVIEWABLE_STATUSES.includes(feature.status)) ? "approved" : "needs_review"}
      actionLabel="Actions"
      primaryAction={null}
      actions={(
        <div className="layer2-actions-stack">
          <section className="workspace-action-group segmented-action-group layer2-actions-row" aria-label="Layer 2 actions">
            <div className="segmented-action-row layer2-inline-actions">
              <WorkspaceActionButton primary onClick={() => onGenerate(pillars.map((pillar) => pillar.id))} disabled={generationRunning || !pillars.length} disabledReason={generationRunning ? "Layer 2 generation is already running." : !pillars.length ? "Keep at least one pillar first." : ""}>Generate all</WorkspaceActionButton>
              <span className="workspace-action-divider" aria-hidden="true" />
              <span className="workspace-action-wrapper layer2-add-feature-action"><Layer2FeatureForm pillars={pillars} onCreate={onCreateFeature} /></span>
              <span className="workspace-action-divider" aria-hidden="true" />
              <WorkspaceActionButton secondary onClick={() => onResearch([])} disabled={researchRunning || !allFeatures.length} disabledReason={researchRunning ? "Layer 2 research is already running." : !allFeatures.length ? "Generate or add features before research." : ""}>Research all</WorkspaceActionButton>
              <span className="workspace-action-divider" aria-hidden="true" />
              <WorkspaceActionButton secondary onClick={onOverlapCritic} disabled={overlapRunning || allFeatures.length < 2} disabledReason={overlapRunning ? "Overlap critique is already running." : allFeatures.length < 2 ? "At least two features are required." : ""}>Run overlap critic</WorkspaceActionButton>
            </div>
          </section>
          <section className="workspace-action-group segmented-action-group layer2-selection-group" aria-label="Selection actions">
            <strong>Selection actions</strong>
            <div className="segmented-action-row layer2-selection-row">
              <WorkspaceActionButton secondary onClick={toggleVisibleFeatures} disabled={!visibleFeatures.length} disabledReason={!visibleFeatures.length ? "No visible features to select." : ""}>Select all</WorkspaceActionButton>
              <span className="workspace-action-divider" aria-hidden="true" />
              <WorkspaceActionButton secondary onClick={() => reviewSelected("keep")} disabled={!selectedIds.length} disabledReason={!selectedIds.length ? "Select features first." : ""}>Keep selected</WorkspaceActionButton>
              <span className="workspace-action-divider" aria-hidden="true" />
              <WorkspaceActionButton secondary destructive={Boolean(selectedIds.length)} onClick={() => reviewSelected("cut")} disabled={!selectedIds.length} disabledReason={!selectedIds.length ? "Select features first." : ""}>Reject selected</WorkspaceActionButton>
              <span className="workspace-action-divider" aria-hidden="true" />
              <WorkspaceActionButton className="layer2-merge-toggle" secondary onClick={() => setReviewOpen((open) => !open)} disabled={!overlapVerdicts.length} disabledReason={!overlapVerdicts.length ? "Run the overlap critic before reviewing conflicts." : ""}>Merge selected</WorkspaceActionButton>
              <span className="workspace-selection-count workspace-selection-summary" aria-live="polite">{selectedIds.length} selected</span>
            </div>
          </section>
        </div>
      )}
      filters={(
        <>
          <WorkspaceFilterField label="Search features" className="workspace-filter-search">
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a feature, description, pillar, or status" aria-label="Search Layer 2 features" />
          </WorkspaceFilterField>
          <WorkspaceFilterField label="Pillar">
            <select value={filters.pillar} onChange={(event) => setFilters({ ...filters, pillar: event.target.value })} aria-label="Filter Layer 2 features by pillar">
              <option value="all">All pillars</option>
              {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
              <option value={UNASSIGNED_PILLAR_ID}>Unassigned</option>
            </select>
          </WorkspaceFilterField>
          <WorkspaceFilterField label="Status">
            <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })} aria-label="Filter Layer 2 features by status">
              <option value="all">All statuses</option>
              {Array.from(new Set(allFeatures.map((feature) => feature.status).filter(Boolean))).sort().map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
            </select>
          </WorkspaceFilterField>
          <WorkspaceFilterField label="View" className="workspace-filter-view">
            <div className="layer2-view-toggle" role="group" aria-label="Layer 2 view mode">
              <button type="button" className={viewMode === "grouped" ? "active" : ""} onClick={() => setViewMode("grouped")}>Grouped</button>
              <button type="button" className={viewMode === "flat" ? "active" : ""} onClick={() => setViewMode("flat")}>Flat</button>
            </div>
          </WorkspaceFilterField>
        </>
      )}
      details={activeFeature ? (
        <DetailDrawer
          feature={activeFeature}
          pillars={pillars}
          pillarById={pillarById}
          graph={graph}
          overlapVerdicts={overlapVerdicts}
          onClose={() => setActiveFeatureId("")}
          onUpdateFeature={onUpdateFeature}
        />
      ) : null}
    >
      <div className={conflictCount || overlapConflictCount ? "status-banner" : "status-banner success"}>
        {conflictCount || overlapConflictCount ? `Critics flagged ${conflictCount + overlapConflictCount} relationship/overlap signal${conflictCount + overlapConflictCount === 1 ? "" : "s"}.` : "No conflicts found."}
      </div>
      <WorkspaceJobNotice jobState={generationJobState} label="Layer 2 generation" onCancel={onCancelJob} />
      <WorkspaceJobNotice jobState={researchJobState} label="Layer 2 research" onCancel={onCancelJob} />
      <WorkspaceJobNotice jobState={overlapJobState} label="Layer 2 overlap critic" onCancel={onCancelJob} />
      {generationJobState?.state === "failed" ? <div className="warning">Layer 2 generation failed. Check Analytics for details.</div> : null}
      {researchJobState?.state === "failed" ? <div className="warning">Layer 2 research failed. Check Analytics for details.</div> : null}
      {overlapJobState?.state === "failed" ? <div className="warning">Layer 2 overlap critic failed. Check Analytics for details.</div> : null}

      {reviewOpen ? (
        <section className="panel overlap-review-panel" aria-label="Layer 2 overlap review">
          <div className="workspace-section-heading">
            <div>
              <strong>Overlap review</strong>
              <p className="muted">Explainable critic verdicts can become graph links, accepted merges, dismissals, or follow-up work.</p>
            </div>
            <select value={reviewFilter} onChange={(event) => setReviewFilter(event.target.value)} aria-label="Filter overlap verdicts">
              <option value="unresolved">Unresolved</option>
              <option value="resolved">Resolved</option>
              <option value="stale_resolution">Stale resolutions</option>
              <option value="all">All</option>
            </select>
          </div>
          {reviewVerdicts.length ? (
            <div className="overlap-review-list">
              {reviewVerdicts.map((verdict) => {
                const target = featureById[verdict.target_id];
                const neighbor = featureById[verdict.neighbor_id];
                const resolved = verdict.resolution_state === "resolved";
                return (
                  <article className="overlap-review-item" key={verdict.id}>
                    <div>
                      <strong>{target ? featureName(target) : verdict.target_id}</strong>
                      <span className="muted"> overlaps with </span>
                      <strong>{neighbor ? featureName(neighbor) : verdict.neighbor_id}</strong>
                      <p className="muted">{relationLabel(verdict.relation)} - confidence {Math.round(Number(verdict.confidence || 0) * 100)}%</p>
                      <p>{verdict.rationale || "No rationale returned."}</p>
                      {verdict.active_resolution ? <p className="muted">Resolved as {relationLabel(verdict.active_resolution.action)}.</p> : null}
                      {verdict.resolution_state === "stale_resolution" ? <p className="warning">Prior decision is stale because one item changed. Rerun or resolve again.</p> : null}
                    </div>
                    <div className="button-row">
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "accept_merge")} disabled={resolved}>Accept merge</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "link")} disabled={resolved}>Link</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "keep_separate")} disabled={resolved}>Keep separate</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "dismiss")} disabled={resolved}>Dismiss</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "needs_followup")} disabled={resolved}>Needs follow-up</button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="muted">No overlap verdicts match this filter.</p>
          )}
        </section>
      ) : null}

      {pillars.length ? (
        visibleFeatures.length ? (
          viewMode === "grouped" ? (
            <div className="layer2-grouped-workbench">
              {groupedFeatures.map((group) => {
                const collapsed = collapsedGroups.includes(group.id);
                const approvedCount = group.features.filter(isApproved).length;
                const needsReviewCount = group.features.filter(isNeedsReview).length;
                return (
                  <section className={group.id === UNASSIGNED_PILLAR_ID ? "layer2-pillar-group unassigned" : "layer2-pillar-group"} key={group.id}>
                    <header className="layer2-pillar-header">
                      <button type="button" className="layer2-group-toggle" onClick={() => toggleGroup(group.id)} aria-expanded={!collapsed}>
                        <span>{collapsed ? "+" : "-"}</span>
                        <strong>{group.title}</strong>
                      </button>
                      <div className="layer2-pillar-metrics">
                        <span>{group.features.length} features</span>
                        <span>{approvedCount} approved</span>
                        <span>{needsReviewCount} needs review</span>
                      </div>
                      <div className="button-row">
                        <button type="button" className="secondary-button" onClick={() => onGenerate([group.id])} disabled={generationRunning || group.id === UNASSIGNED_PILLAR_ID}>Generate features for this pillar</button>
                        <button type="button" className="secondary-button" onClick={() => researchPillar(group.id)} disabled={researchRunning || !group.features.length}>Research this pillar's features</button>
                      </div>
                    </header>
                    {!collapsed ? renderFeatureTable(group.features, `${group.title} features`) : null}
                  </section>
                );
              })}
            </div>
          ) : renderFeatureTable(visibleFeatures)
        ) : (
          <div className="panel guided-empty-state">
            <strong>No features match the current filters.</strong>
            <p className="muted">Clear the search or filters to bring features back into view.</p>
          </div>
        )
      ) : (
        <div className="panel guided-empty-state">
          <strong>No kept pillars yet.</strong>
          <p className="muted">Keep at least one Layer 1 pillar to unlock Layer 2 generation.</p>
        </div>
      )}
    </WorkspacePageLayout>
  );
}
