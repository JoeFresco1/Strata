import { useMemo, useState } from "react";
import CompetitiveIntelligencePanel from "./Layer2CompetitiveIntelligencePanel";
import { FeatureDetail, Layer2FeatureForm } from "./Layer2FeatureWorkbenchParts";
import { FEATURE_STATUSES, featureMatchesFilters, sortFeatureRows } from "./layer2WorkbenchUtils";
import "./Layer2GraphPanel.css";

function Layer2GraphPanel({
  graph,
  pillars,
  onReview,
  onCreateFeature,
  onUpdateFeature,
  onBulkAction,
  onAddEvidence,
  onResearch,
  researchJobs = [],
}) {
  const rows = graph?.workbench?.rows || graph?.features || [];
  const relationships = graph?.relationships || [];
  const coverageMatrix = graph?.coverage_matrix || [];
  const sharedConcerns = graph?.shared_concerns || [];
  const pillarById = Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar]));
  const [selectedIds, setSelectedIds] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [sortKey, setSortKey] = useState("pillar_fit");
  const [filters, setFilters] = useState({ query: "", pillar: "all", status: "all", research: "all", readyOnly: false });

  const visibleRows = useMemo(
    () => sortFeatureRows(rows.filter((row) => featureMatchesFilters(row, filters)), sortKey),
    [rows, filters, sortKey],
  );
  const selectedFeature = rows.find((row) => row.id === selectedId) || visibleRows[0] || null;
  const openReviews = rows.filter((row) => ["candidate", "needs_review"].includes(row.status)).length;
  const layer2Jobs = researchJobs.filter((job) => job.scope === "layer2").slice(0, 4);
  const selectedCount = selectedIds.length;
  const selectedFeaturePillar = selectedFeature ? pillarById[selectedFeature.owner_pillar_id]?.title || "Unassigned" : "";

  function toggleSelected(featureId) {
    setSelectedIds((current) => current.includes(featureId) ? current.filter((item) => item !== featureId) : [...current, featureId]);
  }

  async function bulk(actionType) {
    if (!selectedIds.length || !onBulkAction) return;
    await onBulkAction({ feature_ids: selectedIds, action_type: actionType });
    setSelectedIds([]);
  }

  if (!rows.length) {
    return (
      <div className="panel">
        <div className="panel-header">
          <h3>Layer 2 Feature Workbench</h3>
          {onCreateFeature ? <Layer2FeatureForm pillars={pillars} onCreate={onCreateFeature} /> : null}
        </div>
        <p className="muted">Generate Layer 2 from kept pillars or add a feature manually.</p>
      </div>
    );
  }

  return (
    <div className="panel layer2-graph-panel">
      <div className="panel-header">
        <div>
          <h3>Layer 2 feature workbench</h3>
          <p className="muted">{rows.length} features | {openReviews} open reviews | {relationships.length} relationships</p>
        </div>
        {onCreateFeature ? <Layer2FeatureForm pillars={pillars} onCreate={onCreateFeature} /> : null}
      </div>
      <div className="info-grid">
        <div><strong>Approved features</strong><p>{rows.filter((row) => row.layer3_ready).length}</p></div>
        <div><strong>Manual evidence</strong><p>{rows.reduce((total, row) => total + Number(row.evidence_count || 0), 0)}</p></div>
        <div><strong>Coverage rows</strong><p>{coverageMatrix.length}</p></div>
        <div><strong>Shared concerns</strong><p>{sharedConcerns.length}</p></div>
      </div>
      <div className="layer2-toolbar">
        <input value={filters.query} onChange={(event) => setFilters({ ...filters, query: event.target.value })} placeholder="Search features" />
        <select value={filters.pillar} onChange={(event) => setFilters({ ...filters, pillar: event.target.value })}>
          <option value="all">All pillars</option>
          {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
        </select>
        <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
          <option value="all">All statuses</option>
          {FEATURE_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select value={filters.research} onChange={(event) => setFilters({ ...filters, research: event.target.value })}>
          <option value="all">All research</option>
          <option value="not_started">No evidence</option>
          <option value="manual_evidence">Manual evidence</option>
          <option value="researched">Automated research</option>
        </select>
        <select value={sortKey} onChange={(event) => setSortKey(event.target.value)}>
          <option value="pillar_fit">Sort: fit</option>
          <option value="strategic">Sort: strategic</option>
          <option value="research">Sort: research</option>
          <option value="status">Sort: status</option>
          <option value="name">Sort: name</option>
        </select>
        <label className="checkbox-item">
          <input type="checkbox" checked={filters.readyOnly} onChange={(event) => setFilters({ ...filters, readyOnly: event.target.checked })} />
          <span>Approved only</span>
        </label>
      </div>
      <div className="layer2-bulk-bar">
        <span aria-live="polite">{selectedCount ? `${selectedCount} selected` : `${visibleRows.length} visible`}</span>
        <div className="button-row">
          <button type="button" onClick={() => onResearch?.(selectedIds)} disabled={!selectedIds.length || !onResearch}>Research selected</button>
          <button type="button" className="secondary-button" onClick={() => onResearch?.([])} disabled={!onResearch}>Research all</button>
          <button type="button" className="secondary-button" onClick={() => bulk("approve_for_layer3")} disabled={!selectedIds.length || !onBulkAction}>Approve features</button>
          <button type="button" className="secondary-button" onClick={() => bulk("keep")} disabled={!selectedIds.length || !onBulkAction}>Keep</button>
          <button type="button" className="secondary-button" onClick={() => bulk("needs_review")} disabled={!selectedIds.length || !onBulkAction}>Needs review</button>
          <button type="button" className="secondary-button" onClick={() => bulk("cut")} disabled={!selectedIds.length || !onBulkAction}>Cut</button>
        </div>
      </div>
      {selectedFeature ? (
        <div className="layer2-active-summary">
          <div>
            <span className="layer2-active-kicker">Active feature</span>
            <strong>{selectedFeature.canonical_name}</strong>
            <p className="muted">{selectedFeaturePillar} | {selectedFeature.granularity_class}</p>
          </div>
          <div className="layer2-active-metrics">
            <span className={`status-pill ${selectedFeature.status}`}>{selectedFeature.status}</span>
            <span className="status-pill">{selectedFeature.competitor_coverage_score || 0}% research</span>
            <span className="status-pill">{selectedFeature.evidence_count || 0} evidence</span>
            <span className={`status-pill ${selectedFeature.layer3_ready ? "published" : "needs_review"}`}>
              {selectedFeature.layer3_ready ? "Approved" : "Needs more review"}
            </span>
          </div>
        </div>
      ) : null}
      {layer2Jobs.length ? (
        <div className="layer2-research-jobs">
          {layer2Jobs.map((job) => (
            <div key={job.id} className={`status-card ${job.status}`}>
              <strong>{job.status} | {job.progress}%</strong>
              <span>{job.details?.feature_count || 0} features | {job.details?.pages || 0} pages</span>
              {(job.details?.warnings || []).slice(0, 2).map((warning) => <span key={warning} className="warning-text">{warning}</span>)}
              {job.error ? <span className="warning-text">{job.error}</span> : null}
              {["failed", "completed"].includes(job.status) ? (
                <button type="button" className="secondary-button" onClick={() => onResearch?.(job.details?.feature_ids || [])} disabled={!onResearch}>Retry</button>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      {visibleRows.length ? (
        <div className="layer2-workbench-layout">
          <div className="layer2-table-wrap">
            <table className="layer2-feature-table">
              <thead>
                <tr>
                  <th scope="col">Select</th>
                  <th scope="col">Feature</th>
                  <th scope="col">Pillar</th>
                  <th scope="col">Status</th>
                  <th scope="col">Fit</th>
                  <th scope="col">Strategic</th>
                  <th scope="col">Research</th>
                  <th scope="col">Ready</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.id} className={selectedId === row.id ? "selected" : ""} aria-selected={selectedId === row.id}>
                    <td><input type="checkbox" aria-label={`Select ${row.canonical_name} for bulk actions`} checked={selectedIds.includes(row.id)} onChange={() => toggleSelected(row.id)} /></td>
                    <td>
                      <button type="button" className="layer2-feature-select" onClick={() => setSelectedId(row.id)} aria-current={selectedId === row.id ? "true" : undefined}>
                        <strong>{row.canonical_name}</strong>
                        <span>{row.granularity_class}</span>
                      </button>
                    </td>
                    <td>{pillarById[row.owner_pillar_id]?.title || "Unassigned"}</td>
                    <td><span className={`status-pill ${row.status}`}>{row.status}</span></td>
                    <td>{row.pillar_fit_score}</td>
                    <td>{row.strategic_value_score}</td>
                    <td>{row.competitor_coverage_score || 0}%</td>
                    <td>{row.layer3_ready ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="layer2-mobile-list" aria-label="Layer 2 feature rows">
            {visibleRows.map((row) => (
              <article key={row.id} className={selectedId === row.id ? "layer2-mobile-card selected" : "layer2-mobile-card"} aria-current={selectedId === row.id ? "true" : undefined}>
                <div className="layer2-mobile-card-head">
                  <label className="checkbox-item">
                    <input type="checkbox" checked={selectedIds.includes(row.id)} onChange={() => toggleSelected(row.id)} />
                    <span>Select</span>
                  </label>
                  <span className={`status-pill ${row.status}`}>{row.status}</span>
                </div>
                <button type="button" className="layer2-feature-select" onClick={() => setSelectedId(row.id)}>
                  <strong>{row.canonical_name}</strong>
                  <span>{pillarById[row.owner_pillar_id]?.title || "Unassigned"} | {row.granularity_class}</span>
                </button>
                <div className="layer2-mobile-metrics">
                  <span>Fit {row.pillar_fit_score}</span>
                  <span>Strategic {row.strategic_value_score}</span>
                  <span>Research {row.competitor_coverage_score || 0}%</span>
                  <span>{row.layer3_ready ? "Approved" : "Needs review"}</span>
                </div>
              </article>
            ))}
          </div>
          <FeatureDetail
            feature={selectedFeature}
            pillars={pillars}
            onUpdate={onUpdateFeature}
            onReview={onReview}
            onAddEvidence={onAddEvidence}
          />
        </div>
      ) : (
        <div className="panel layer2-empty-state">
          <strong>No features match the current filters.</strong>
          <p className="muted">Adjust the search, pillar, status, or research filters to bring capabilities back into view.</p>
        </div>
      )}
      {sharedConcerns.length ? (
        <div className="layer2-owner-group">
          <h4>Shared concerns</h4>
          <div className="layer2-chip-grid">
            {sharedConcerns.map((concern) => (
              <span key={concern.id} className="status-pill">{concern.concern_type}: {concern.name}</span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export { CompetitiveIntelligencePanel };
export default Layer2GraphPanel;
