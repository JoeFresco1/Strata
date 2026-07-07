import { useMemo, useState } from "react";
import { Layer2FeatureForm } from "../Layer2FeatureWorkbenchParts";
import ColumnHeader from "./ColumnHeader";
import { layer1Pillars, statusLabel } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceActionGroup, WorkspaceStatusBadge } from "./WorkspacePage";
import WorkspaceJobNotice from "./WorkspaceJobNotice";

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

export default function Layer2View({
  snapshot,
  onGenerate,
  onReview,
  onCreateFeature,
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
  const allFeatures = graph?.workbench?.rows || graph?.features || [];
  const pillarById = useMemo(() => Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar])), [pillars]);
  const conflictCount = (graph.relationships || []).filter((relationship) => ["overlaps_with", "duplicate_of", "conflicts_with"].includes(relationship.relationship_type)).length;
  const [selectedIds, setSelectedIds] = useState([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ pillar: "all", status: "all" });
  const [sortConfig, setSortConfig] = useState({ key: "pillar", direction: "asc" });
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewFilter, setReviewFilter] = useState("unresolved");
  const generationRunning = generationJobState?.state === "running";
  const researchRunning = researchJobState?.state === "running";
  const overlapRunning = overlapJobState?.state === "running";
  const overlapVerdicts = snapshot?.overlap?.layer2?.verdicts || [];
  const overlapConflictCount = overlapVerdicts.filter((verdict) => verdict.relation !== "distinct").length;
  const featureById = useMemo(() => Object.fromEntries(allFeatures.map((feature) => [feature.id, feature])), [allFeatures]);
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
      const text = [feature.canonical_name, feature.description, feature.feature_type, feature.granularity_class, feature.status, pillarById[feature.owner_pillar_id]?.title]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return (
        (!normalizedQuery || text.includes(normalizedQuery)) &&
        (filters.pillar === "all" || feature.owner_pillar_id === filters.pillar) &&
        (filters.status === "all" || feature.status === filters.status)
      );
    });
    return [...filtered].sort((left, right) => {
      const selectors = {
        name: (feature) => feature.canonical_name,
        pillar: (feature) => pillarById[feature.owner_pillar_id]?.title || "Unassigned",
        status: (feature) => feature.status,
        fit: (feature) => score(feature.pillar_fit_score),
        strategic: (feature) => score(feature.strategic_value_score),
        research: (feature) => score(feature.competitor_coverage_score),
      };
      const select = selectors[sortConfig.key] || selectors.pillar;
      return compareValues(select(left), select(right), sortConfig.direction) || left.canonical_name.localeCompare(right.canonical_name);
    });
  }, [allFeatures, filters, pillarById, query, sortConfig]);
  function toggleFeature(id) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleVisibleFeatures() {
    const visibleIds = visibleFeatures.map((feature) => feature.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
    setSelectedIds((current) => allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : Array.from(new Set([...current, ...visibleIds])));
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

  return (
    <WorkspacePageLayout
      id="workspace-panel-layer2"
      ariaLabel="Layer 2 features"
      title="Features"
      description="Generate, research, and approve concrete features under the kept product pillars."
      status={!allFeatures.length ? "draft" : allFeatures.every((feature) => !["candidate", "needs_review"].includes(feature.status)) ? "approved" : "needs_review"}
      primaryAction={(
        <WorkspaceActionButton
          primary
          onClick={() => onGenerate(pillars.map((pillar) => pillar.id))}
          disabled={generationRunning || !pillars.length}
          disabledReason={generationRunning ? "Layer 2 generation is already running." : !pillars.length ? "Keep at least one pillar first." : ""}
        >
          Generate all
        </WorkspaceActionButton>
      )}
      actions={(
        <>
          <WorkspaceActionGroup label="Generate">
            <Layer2FeatureForm pillars={pillars} onCreate={onCreateFeature} />
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Research">
            <WorkspaceActionButton
              secondary
              onClick={() => onResearch([])}
              disabled={researchRunning || !allFeatures.length}
              disabledReason={researchRunning ? "Layer 2 research is already running." : !allFeatures.length ? "Generate or add features before research." : ""}
            >
              Research all
            </WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Review / Critique">
            <WorkspaceActionButton
              secondary
              onClick={onOverlapCritic}
              disabled={overlapRunning || allFeatures.length < 2}
              disabledReason={overlapRunning ? "Overlap critique is already running." : allFeatures.length < 2 ? "At least two features are required." : ""}
            >
              Run overlap critic
            </WorkspaceActionButton>
            <WorkspaceActionButton
              secondary
              onClick={() => setReviewOpen((open) => !open)}
              disabled={!overlapVerdicts.length}
              disabledReason={!overlapVerdicts.length ? "Run the overlap critic before reviewing verdicts." : ""}
            >
              Review selected ({overlapVerdicts.filter((verdict) => verdict.relation !== "distinct" && (verdict.resolution_state || "unresolved") !== "resolved").length})
            </WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Selection actions">
            <WorkspaceActionButton secondary onClick={toggleVisibleFeatures} disabled={!visibleFeatures.length} disabledReason={!visibleFeatures.length ? "No visible features to select." : ""}>Select all</WorkspaceActionButton>
            <WorkspaceActionButton secondary onClick={() => reviewSelected("keep")} disabled={!selectedIds.length} disabledReason={!selectedIds.length ? "Select features first." : ""}>Keep selected</WorkspaceActionButton>
            <WorkspaceActionButton secondary onClick={() => reviewSelected("approve_for_layer3")} disabled={!selectedIds.length} disabledReason={!selectedIds.length ? "Select features first." : ""}>Approve selected</WorkspaceActionButton>
            <WorkspaceActionButton secondary destructive={Boolean(selectedIds.length)} onClick={() => reviewSelected("cut")} disabled={!selectedIds.length} disabledReason={!selectedIds.length ? "Select features first." : ""}>Reject selected</WorkspaceActionButton>
            <span className="workspace-selection-count" aria-live="polite">{selectedIds.length ? `${selectedIds.length} selected` : `${visibleFeatures.length} of ${allFeatures.length} features`}</span>
          </WorkspaceActionGroup>
        </>
      )}
      filters={(
        <>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search features" aria-label="Search Layer 2 features" />
        <select value={filters.pillar} onChange={(event) => setFilters({ ...filters, pillar: event.target.value })} aria-label="Filter Layer 2 features by pillar">
          <option value="all">All pillars</option>
          {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
        </select>
        <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })} aria-label="Filter Layer 2 features by status">
          <option value="all">All statuses</option>
          {Array.from(new Set(allFeatures.map((feature) => feature.status).filter(Boolean))).sort().map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
        </select>
        <label>
          Sort by
          <select value={sortConfig.key} onChange={(event) => setSortConfig({ ...sortConfig, key: event.target.value })} aria-label="Sort features">
            <option value="pillar">Pillar</option>
            <option value="name">Feature</option>
            <option value="status">Status</option>
            <option value="fit">Fit</option>
            <option value="strategic">Strategic</option>
            <option value="research">Research</option>
          </select>
        </label>
        <WorkspaceActionButton secondary onClick={() => setSortConfig((current) => ({ ...current, direction: current.direction === "asc" ? "desc" : "asc" }))}>
          {sortConfig.direction === "asc" ? "Ascending" : "Descending"}
        </WorkspaceActionButton>
        </>
      )}
    >

      <div className={conflictCount ? "status-banner" : "status-banner success"}>
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
                      <strong>{target?.canonical_name || verdict.target_id}</strong>
                      <span className="muted"> overlaps with </span>
                      <strong>{neighbor?.canonical_name || verdict.neighbor_id}</strong>
                      <p className="muted">{relationLabel(verdict.relation)} · confidence {Math.round(Number(verdict.confidence || 0) * 100)}%</p>
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
          <div className="workspace-table-wrap">
            <table className="workspace-review-table">
              <thead>
                <tr>
                  <th scope="col"><ColumnHeader label="Select" description="Choose one or more features for bulk review actions." /></th>
                  <th scope="col"><ColumnHeader label="Feature" description="The Layer 2 capability candidate and its product description." sortKey="name" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                  <th scope="col"><ColumnHeader label="Pillar" description="The Layer 1 pillar that currently owns this feature." sortKey="pillar" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                  <th scope="col"><ColumnHeader label="Status" description="Current review state, such as generated, kept, approved, or rejected." sortKey="status" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                  <th scope="col"><ColumnHeader label="Fit" description="How strongly this feature belongs under its assigned pillar." sortKey="fit" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                  <th scope="col"><ColumnHeader label="Strategic" description="Estimated product value or planning importance for this feature." sortKey="strategic" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                  <th scope="col"><ColumnHeader label="Research" description="Competitor coverage score from feature-level competitive research." sortKey="research" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                  <th scope="col"><ColumnHeader label="Actions" description="Row-level controls to keep, approve for Layer 3, reject, or research this feature." /></th>
                </tr>
              </thead>
              <tbody>
                {visibleFeatures.map((feature) => {
                  const warnings = featureWarnings(feature, graph, overlapVerdicts);
                  const warning = warnings[0];
                  return (
                    <tr key={feature.id}>
                      <td><input type="checkbox" checked={selectedIds.includes(feature.id)} onChange={() => toggleFeature(feature.id)} aria-label={`Select ${feature.canonical_name}`} /></td>
                      <td>
                        <strong>
                          {feature.canonical_name}
                          {warning ? <span className="warning-icon" title={`${warning.source}: ${warning.detail}`} aria-label={`Warning for ${feature.canonical_name}`}>!</span> : null}
                        </strong>
                        <p className="muted">{feature.description || "No description yet."}</p>
                        {warning ? <p className="muted critic-source-line">{warnings.map((item) => `${item.source}: ${item.label.replaceAll("_", " ")}`).join(" | ")}</p> : null}
                      </td>
                      <td>{pillarById[feature.owner_pillar_id]?.title || "Unassigned"}</td>
                      <td><WorkspaceStatusBadge status={feature.status} /></td>
                      <td>{feature.pillar_fit_score ?? "-"}</td>
                      <td>{feature.strategic_value_score ?? "-"}</td>
                      <td>{feature.competitor_coverage_score ?? 0}%</td>
                      <td>
                        <div className="button-row">
                          <button type="button" className="secondary-button" onClick={() => onReview({ action_type: "keep", feature_id: feature.id })}>Keep</button>
                          <button type="button" className="secondary-button" onClick={() => onReview({ action_type: "approve_for_layer3", feature_id: feature.id })}>Approve</button>
                          <button type="button" className="secondary-button danger-button" onClick={() => onReview({ action_type: "cut", feature_id: feature.id })}>Reject</button>
                          <button type="button" className="secondary-button" onClick={() => onResearch([feature.id])} disabled={researchRunning} title={researchRunning ? "Layer 2 research is already running." : "Research this row"}>Research row</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
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
