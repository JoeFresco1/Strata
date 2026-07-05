import { useMemo, useState } from "react";
import { Layer2FeatureForm } from "../Layer2FeatureWorkbenchParts";
import { layer1Pillars } from "./workspaceSelectors";

function featureHasWarning(feature, graph) {
  const relationships = graph?.relationships || [];
  return relationships.find((relationship) => (
    relationship.source_feature_id === feature.id || relationship.target_feature_id === feature.id
  ) && ["overlaps_with", "duplicate_of", "conflicts_with"].includes(relationship.relationship_type));
}

function score(value) {
  return Number(value || 0);
}

export default function Layer2View({
  snapshot,
  onGenerate,
  onReview,
  onCreateFeature,
  onResearch,
  generationJobState,
  researchJobState,
}) {
  const pillars = layer1Pillars(snapshot).filter((pillar) => ["kept", "prioritized"].includes(pillar.status));
  const graph = snapshot?.layer2_graph || {};
  const allFeatures = graph?.workbench?.rows || graph?.features || [];
  const pillarById = useMemo(() => Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar])), [pillars]);
  const conflictCount = (graph.relationships || []).filter((relationship) => ["overlaps_with", "duplicate_of", "conflicts_with"].includes(relationship.relationship_type)).length;
  const [selectedIds, setSelectedIds] = useState([]);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ pillar: "all", status: "all" });
  const [sortKey, setSortKey] = useState("pillar");
  const generationRunning = generationJobState?.state === "running";
  const researchRunning = researchJobState?.state === "running";
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
      if (sortKey === "name") return left.canonical_name.localeCompare(right.canonical_name);
      if (sortKey === "status") return (left.status || "").localeCompare(right.status || "");
      if (sortKey === "fit") return score(right.pillar_fit_score) - score(left.pillar_fit_score);
      if (sortKey === "strategic") return score(right.strategic_value_score) - score(left.strategic_value_score);
      if (sortKey === "research") return score(right.competitor_coverage_score) - score(left.competitor_coverage_score);
      return (pillarById[left.owner_pillar_id]?.title || "").localeCompare(pillarById[right.owner_pillar_id]?.title || "") || left.canonical_name.localeCompare(right.canonical_name);
    });
  }, [allFeatures, filters, pillarById, query, sortKey]);
  function toggleFeature(id) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function toggleVisibleFeatures() {
    const visibleIds = visibleFeatures.map((feature) => feature.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
    setSelectedIds((current) => allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : Array.from(new Set([...current, ...visibleIds])));
  }

  async function reviewSelected(actionType) {
    const targets = selectedIds.filter((id) => allFeatures.some((feature) => feature.id === id));
    await Promise.all(targets.map((id) => onReview({ action_type: actionType, feature_id: id })));
    setSelectedIds((current) => current.filter((id) => !targets.includes(id)));
  }

  return (
    <section className="workspace-layer-panel" id="workspace-panel-layer2" role="tabpanel" aria-label="Layer 2 features">
      <div className="workspace-toolbar panel">
        <button type="button" onClick={() => onGenerate(pillars.map((pillar) => pillar.id))} disabled={generationRunning || !pillars.length}>
          {generationRunning ? "Generating..." : generationJobState?.state === "failed" ? "Retry generation" : "Generate features"}
        </button>
        <button type="button" className="secondary-button" onClick={() => onResearch([])} disabled={researchRunning}>
          {researchRunning ? "Research running..." : researchJobState?.state === "failed" ? "Retry competitive research" : "Run competitive research"}
        </button>
        <button type="button" className="secondary-button" disabled title="Layer 2 critics run inside the current generation/review pipeline. No separate critic route exists yet.">Run critics</button>
        <Layer2FeatureForm pillars={pillars} onCreate={onCreateFeature} />
      </div>

      <div className="workspace-list-controls panel">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search features" aria-label="Search Layer 2 features" />
        <select value={filters.pillar} onChange={(event) => setFilters({ ...filters, pillar: event.target.value })} aria-label="Filter Layer 2 features by pillar">
          <option value="all">All pillars</option>
          {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
        </select>
        <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })} aria-label="Filter Layer 2 features by status">
          <option value="all">All statuses</option>
          {Array.from(new Set(allFeatures.map((feature) => feature.status).filter(Boolean))).sort().map((status) => <option key={status} value={status}>{status}</option>)}
        </select>
        <select value={sortKey} onChange={(event) => setSortKey(event.target.value)} aria-label="Sort Layer 2 features">
          <option value="pillar">Sort by pillar</option>
          <option value="name">Sort by name</option>
          <option value="status">Sort by status</option>
          <option value="fit">Sort by fit</option>
          <option value="strategic">Sort by strategic value</option>
          <option value="research">Sort by research</option>
        </select>
        <button type="button" className="secondary-button" onClick={toggleVisibleFeatures} disabled={!visibleFeatures.length}>Select visible</button>
        <button type="button" className="secondary-button" onClick={() => reviewSelected("keep")} disabled={!selectedIds.length}>Keep selected</button>
        <button type="button" className="secondary-button" onClick={() => reviewSelected("approve_for_layer3")} disabled={!selectedIds.length}>Approve selected</button>
        <button type="button" className="secondary-button" onClick={() => reviewSelected("cut")} disabled={!selectedIds.length}>Reject selected</button>
        <span aria-live="polite">{selectedIds.length ? `${selectedIds.length} selected` : `${visibleFeatures.length} of ${allFeatures.length} features`}</span>
      </div>

      <div className={conflictCount ? "status-banner" : "status-banner success"}>
        {conflictCount ? `Critics flagged ${conflictCount} relationship conflict${conflictCount === 1 ? "" : "s"}.` : "No conflicts found."}
      </div>
      {generationJobState?.state === "failed" ? <div className="warning">Layer 2 generation failed. Check Analytics for details.</div> : null}
      {researchJobState?.state === "failed" ? <div className="warning">Layer 2 research failed. Check Analytics for details.</div> : null}

      {pillars.length ? (
        visibleFeatures.length ? (
          <div className="workspace-table-wrap">
            <table className="workspace-review-table">
              <thead>
                <tr>
                  <th scope="col">Select</th>
                  <th scope="col">Feature</th>
                  <th scope="col">Pillar</th>
                  <th scope="col">Status</th>
                  <th scope="col">Fit</th>
                  <th scope="col">Strategic</th>
                  <th scope="col">Research</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleFeatures.map((feature) => {
                  const warning = featureHasWarning(feature, graph);
                  return (
                    <tr key={feature.id}>
                      <td><input type="checkbox" checked={selectedIds.includes(feature.id)} onChange={() => toggleFeature(feature.id)} aria-label={`Select ${feature.canonical_name}`} /></td>
                      <td>
                        <strong>
                          {feature.canonical_name}
                          {warning ? <span className="warning-icon" title={warning.rationale || warning.reason || warning.relationship_type} aria-label={`Warning for ${feature.canonical_name}`}>!</span> : null}
                        </strong>
                        <p className="muted">{feature.description || "No description yet."}</p>
                      </td>
                      <td>{pillarById[feature.owner_pillar_id]?.title || "Unassigned"}</td>
                      <td><span className={`status-pill ${feature.status}`}>{feature.status}</span></td>
                      <td>{feature.pillar_fit_score ?? "-"}</td>
                      <td>{feature.strategic_value_score ?? "-"}</td>
                      <td>{feature.competitor_coverage_score ?? 0}%</td>
                      <td>
                        <div className="button-row">
                          <button type="button" className="secondary-button" onClick={() => onReview({ action_type: "keep", feature_id: feature.id })}>Keep</button>
                          <button type="button" className="secondary-button" onClick={() => onReview({ action_type: "approve_for_layer3", feature_id: feature.id })}>Approve</button>
                          <button type="button" className="secondary-button" onClick={() => onReview({ action_type: "cut", feature_id: feature.id })}>Reject</button>
                          <button type="button" className="secondary-button" onClick={() => onResearch([feature.id])} disabled={researchRunning}>Research</button>
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
    </section>
  );
}
