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
          <h3>Layer 2 Feature Workbench</h3>
          <p className="muted">{rows.length} features | {openReviews} open reviews | {relationships.length} relationships</p>
        </div>
        {onCreateFeature ? <Layer2FeatureForm pillars={pillars} onCreate={onCreateFeature} /> : null}
      </div>
      <div className="info-grid">
        <div><strong>Ready For Layer 3</strong><p>{rows.filter((row) => row.layer3_ready).length}</p></div>
        <div><strong>Manual Evidence</strong><p>{rows.reduce((total, row) => total + Number(row.evidence_count || 0), 0)}</p></div>
        <div><strong>Coverage Rows</strong><p>{coverageMatrix.length}</p></div>
        <div><strong>Shared Concerns</strong><p>{sharedConcerns.length}</p></div>
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
          <span>Layer 3 ready</span>
        </label>
      </div>
      <div className="button-row">
        <button type="button" className="secondary-button" onClick={() => bulk("approve_for_layer3")} disabled={!selectedIds.length || !onBulkAction}>Bulk Approve</button>
        <button type="button" className="secondary-button" onClick={() => bulk("keep")} disabled={!selectedIds.length || !onBulkAction}>Bulk Keep</button>
        <button type="button" className="secondary-button" onClick={() => bulk("needs_review")} disabled={!selectedIds.length || !onBulkAction}>Bulk Needs Review</button>
        <button type="button" className="secondary-button" onClick={() => bulk("cut")} disabled={!selectedIds.length || !onBulkAction}>Bulk Cut</button>
      </div>
      <div className="layer2-workbench-layout">
        <div className="layer2-table-wrap">
          <table className="layer2-feature-table">
            <thead>
              <tr>
                <th />
                <th>Feature</th>
                <th>Pillar</th>
                <th>Status</th>
                <th>Fit</th>
                <th>Strategic</th>
                <th>Research</th>
                <th>Ready</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <tr key={row.id} className={selectedId === row.id ? "selected" : ""} onClick={() => setSelectedId(row.id)}>
                  <td><input type="checkbox" checked={selectedIds.includes(row.id)} onChange={() => toggleSelected(row.id)} onClick={(event) => event.stopPropagation()} /></td>
                  <td><strong>{row.canonical_name}</strong><span>{row.granularity_class}</span></td>
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
        <FeatureDetail
          feature={selectedFeature}
          pillars={pillars}
          onUpdate={onUpdateFeature}
          onReview={onReview}
          onAddEvidence={onAddEvidence}
        />
      </div>
      {sharedConcerns.length ? (
        <div className="layer2-owner-group">
          <h4>Shared Concerns</h4>
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
