import { useEffect, useMemo, useState } from "react";
import TreeDashboard, { NodeDetail } from "./treeDashboard";
import { flattenWorkspaceTree } from "./projectWorkspaceData";
import "./LivingWorkspace.css";

function WorkspaceTable({
  root,
  selectedId,
  tableScope,
  tableState,
  onTableScopeChange,
  onTableStateChange,
  onSelect,
  onBulkNodeStatus,
  onBulkFeatureStatus,
}) {
  const allRows = useMemo(() => flattenWorkspaceTree(root), [root]);
  const selected = allRows.find((row) => row.id === selectedId) || allRows[0];
  const [checked, setChecked] = useState([]);
  const visibleRows = useMemo(() => {
    const query = String(tableState?.query || "").trim().toLowerCase();
    const entityType = tableState?.entity_type || "all";
    const status = tableState?.status || "all";
    const sort = tableState?.sort || "hierarchy";
    const scoped = tableScope === "project" || !selected || selected.entity_type === "brief"
      ? allRows
      : selected.entity_type === "pillar"
        ? allRows.filter((row) => row.id === selected.id || row.parent_id === selected.id)
        : allRows.filter((row) => row.id === selected.id || row.parent_id === selected.parent_id);
    const filtered = scoped.filter((row) => (
      (!query || `${row.title} ${row.description}`.toLowerCase().includes(query))
      && (entityType === "all" || row.entity_type === entityType)
      && (status === "all" || row.status === status)
    ));
    if (sort === "name") return [...filtered].sort((left, right) => left.title.localeCompare(right.title));
    if (sort === "status") return [...filtered].sort((left, right) => String(left.status).localeCompare(String(right.status)));
    return filtered;
  }, [allRows, selected, tableScope, tableState]);

  useEffect(() => setChecked((current) => current.filter((id) => visibleRows.some((row) => row.id === id))), [visibleRows]);
  const checkedTypes = new Set(visibleRows.filter((row) => checked.includes(row.id)).map((row) => row.entity_type));
  const invalidBulkSelection = checkedTypes.size > 1;

  async function applyBulk(status) {
    const rows = visibleRows.filter((row) => checked.includes(row.id) && row.entity_type !== "brief");
    const types = new Set(rows.map((row) => row.entity_type));
    if (types.size !== 1) return;
    if (types.has("feature")) await onBulkFeatureStatus?.(rows.map((row) => row.id), status);
    if (types.has("pillar")) await onBulkNodeStatus?.(rows.map((row) => row.id), status);
    setChecked([]);
  }

  return (
    <div className="workspace-table panel">
      <div className="panel-header">
        <div>
          <h3>Project Table</h3>
          <p className="muted">{visibleRows.length} visible entities</p>
        </div>
        <div className="segmented">
          <button type="button" className={tableScope === "focused" ? "active" : ""} onClick={() => onTableScopeChange("focused")}>Focused branch</button>
          <button type="button" className={tableScope === "project" ? "active" : ""} onClick={() => onTableScopeChange("project")}>Entire project</button>
        </div>
      </div>
      <div className="button-row">
        <button type="button" className="secondary-button" disabled={!checked.length || invalidBulkSelection} onClick={() => applyBulk("kept")}>Keep</button>
        <button type="button" className="secondary-button" disabled={!checked.length || invalidBulkSelection} onClick={() => applyBulk("prioritized")}>Prioritize</button>
        <button type="button" className="secondary-button" disabled={!checked.length || invalidBulkSelection} onClick={() => applyBulk("cut")}>Cut</button>
        {invalidBulkSelection ? <span className="warning-text">Select only pillars or only features for bulk actions.</span> : null}
      </div>
      <div className="layer2-toolbar">
        <input
          value={tableState?.query || ""}
          onChange={(event) => onTableStateChange({ ...tableState, query: event.target.value })}
          placeholder="Search this table"
        />
        <select value={tableState?.entity_type || "all"} onChange={(event) => onTableStateChange({ ...tableState, entity_type: event.target.value })}>
          <option value="all">All entity types</option>
          <option value="brief">Brief</option>
          <option value="pillar">Pillars</option>
          <option value="feature">Features</option>
        </select>
        <select value={tableState?.status || "all"} onChange={(event) => onTableStateChange({ ...tableState, status: event.target.value })}>
          <option value="all">All statuses</option>
          {["draft", "published", "generated", "candidate", "needs_review", "kept", "prioritized", "approved", "cut", "merged"].map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select value={tableState?.sort || "hierarchy"} onChange={(event) => onTableStateChange({ ...tableState, sort: event.target.value })}>
          <option value="hierarchy">Hierarchy order</option>
          <option value="name">Name</option>
          <option value="status">Status</option>
        </select>
      </div>
      <div className="workspace-table-scroll">
        <table>
          <thead><tr><th /><th>Entity</th><th>Type</th><th>Status</th><th>Priority</th><th>Parent</th></tr></thead>
          <tbody>
            {visibleRows.map((row) => (
              <tr key={row.id} className={row.id === selectedId ? "selected" : ""} onClick={() => onSelect(row.id)}>
                <td>
                  {row.entity_type !== "brief" ? (
                    <input
                      type="checkbox"
                      checked={checked.includes(row.id)}
                      onClick={(event) => event.stopPropagation()}
                      onChange={() => setChecked((current) => current.includes(row.id) ? current.filter((id) => id !== row.id) : [...current, row.id])}
                    />
                  ) : null}
                </td>
                <td style={{ paddingLeft: `${12 + row.depth * 18}px` }}><strong>{row.title}</strong><span>{row.description}</span></td>
                <td>{row.entity_type}</td>
                <td>{row.status}</td>
                <td>{row.priority ?? "—"}</td>
                <td>{allRows.find((item) => item.id === row.parent_id)?.title || "Root"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function LivingWorkspace({
  project,
  brief,
  tree,
  layer2Graph,
  findings,
  researchJobs,
  workspaceState,
  onWorkspaceStateChange,
  onSaveBrief,
  onPublishBrief,
  onSaveNode,
  onUpdateFeature,
  onCreateFeature,
  onReviewFeature,
  onAddEvidence,
  onResearchLayer1,
  onResearchLayer2,
  onGenerateLayer1,
  onGenerateLayer2,
  onBulkFeatureStatus,
  onBulkNodeStatus,
  generationControls,
}) {
  const root = tree?.[0] || null;
  const selectedId = workspaceState?.selected_entity_id || "layer0-root";
  const viewMode = workspaceState?.view_mode || "map";
  const tableScope = workspaceState?.table_scope || "focused";
  const tableState = workspaceState?.table_state || {};
  const flatRows = useMemo(() => flattenWorkspaceTree(root), [root]);
  const selectedEntity = flatRows.find((item) => item.id === selectedId) || root;
  const parentEntity = flatRows.find((item) => item.id === selectedEntity?.parent_id) || null;
  const childEntities = flatRows.filter((item) => item.parent_id === selectedEntity?.id);
  const overlapLinks = (layer2Graph?.relationships || [])
    .filter((edge) => edge.source_feature_id === selectedEntity?.id || edge.target_feature_id === selectedEntity?.id)
    .map((edge) => ({
      id: edge.id,
      type: edge.relationship_type,
      detail: edge.reason || edge.relationship_type,
      target: flatRows.find((item) => item.id === (edge.source_feature_id === selectedEntity?.id ? edge.target_feature_id : edge.source_feature_id)),
    }))
    .filter((edge) => edge.target);
  const pillars = flatRows.filter((item) => item.entity_type === "pillar");

  function patchState(patch) {
    onWorkspaceStateChange({ ...workspaceState, ...patch });
  }

  return (
    <section className="living-workspace">
      <div className="workspace-command-bar panel">
        <div>
          <h3>Living Product Workspace</h3>
          <p className="muted">Move through the product as a tree, compare it as a table, or ask the assistant about the current branch.</p>
        </div>
        <div className="segmented">
          <button type="button" className={viewMode === "map" ? "active" : ""} onClick={() => patchState({ view_mode: "map" })}>Map</button>
          <button type="button" className={viewMode === "table" ? "active" : ""} onClick={() => patchState({ view_mode: "table" })}>Table</button>
        </div>
      </div>

      {viewMode === "map" ? (
        <TreeDashboard
          project={project}
          brief={brief}
          tree={root?.children || []}
          findings={findings}
          researchJobs={researchJobs}
          layer2Graph={layer2Graph}
          selectedId={selectedId}
          mapState={workspaceState?.map_state || {}}
          onSelectionChange={(entity) => patchState({
            selected_entity_id: entity.id,
            selected_entity_type: entity.entity_type,
          })}
          onMapStateChange={(map_state) => patchState({ map_state })}
          onSaveBrief={onSaveBrief}
          onPublishBrief={onPublishBrief}
          onSaveNode={onSaveNode}
          onUpdateFeature={onUpdateFeature}
          onCreateFeature={onCreateFeature}
          onReviewFeature={onReviewFeature}
          onAddEvidence={onAddEvidence}
          onResearchLayer1={onResearchLayer1}
          onResearchLayer2={onResearchLayer2}
          onGenerateLayer1={onGenerateLayer1}
          onGenerateLayer2={onGenerateLayer2}
          generationControls={generationControls}
        />
      ) : (
        <div className="workspace-table-layout">
          <WorkspaceTable
            root={root}
            selectedId={selectedId}
            tableScope={tableScope}
            tableState={tableState}
            onTableScopeChange={(table_scope) => patchState({ table_scope })}
            onTableStateChange={(table_state) => patchState({ table_state })}
            onSelect={(id) => {
              const row = flatRows.find((item) => item.id === id);
              if (row) patchState({ selected_entity_id: row.id, selected_entity_type: row.entity_type });
            }}
            onBulkNodeStatus={onBulkNodeStatus}
            onBulkFeatureStatus={onBulkFeatureStatus}
          />
          <div className="panel workspace-table-inspector">
            <NodeDetail
              node={selectedEntity}
              brief={brief}
              findings={findings}
              parentNode={parentEntity}
              childNodes={childEntities}
              overlapLinks={overlapLinks}
              onSelectNode={(id) => {
                const row = flatRows.find((item) => item.id === id);
                if (row) patchState({ selected_entity_id: row.id, selected_entity_type: row.entity_type });
              }}
              onSaveNode={onSaveNode}
              pillars={pillars}
              onSaveBrief={onSaveBrief}
              onPublishBrief={onPublishBrief}
              onUpdateFeature={onUpdateFeature}
              onCreateFeature={onCreateFeature}
              onReviewFeature={onReviewFeature}
              onAddEvidence={onAddEvidence}
              onResearchLayer1={onResearchLayer1}
              onResearchLayer2={onResearchLayer2}
              onGenerateLayer1={onGenerateLayer1}
              onGenerateLayer2={onGenerateLayer2}
              generationControls={generationControls}
            />
          </div>
        </div>
      )}
    </section>
  );
}
