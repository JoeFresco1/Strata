import "./treeDashboard.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { FeatureDetail, Layer2FeatureForm } from "./Layer2FeatureWorkbenchParts";
import {
  CANVAS_PADDING,
  HORIZONTAL_GAP,
  MAX_ZOOM,
  MIN_ZOOM,
  NODE_HEIGHT,
  NODE_WIDTH,
  OVERLAP_MODE_OPTIONS,
  STATUS_OPTIONS,
  buildRootNode,
  buildTreeIndex,
  buildVisibleGraph,
  clamp,
  collectOverlapEdges,
  collectVisibleIds,
  createInitialCollapsedSet,
  detailRowsForNode,
  filterTree,
  formatLayerLabel,
  formatNodeType,
  nodeTone,
  withDerivedFields,
} from "./treeDashboardData";

// Shows compact counts for total, visible, overlap, and per-layer nodes.
function DashboardStats({ stats }) {
  return (
    <div className="tree-stats-grid">
      <div className="tree-stat">
        <span>Total Nodes</span>
        <strong>{stats.totalNodes}</strong>
      </div>
      <div className="tree-stat">
        <span>Visible Nodes</span>
        <strong>{stats.visibleNodes}</strong>
      </div>
      <div className="tree-stat">
        <span>Overlap Count</span>
        <strong>{stats.overlapEdges}</strong>
      </div>
      <div className="tree-stat">
        <span>Map Depth</span>
        <strong>{stats.depth}</strong>
      </div>
      {[0, 1, 2, 3].map((layer) => (
        <div key={layer} className="tree-stat compact">
          <span>{formatLayerLabel(layer)}</span>
          <strong>{stats.perLayer[layer] || 0}</strong>
        </div>
      ))}
    </div>
  );
}

// Provides layer-specific filter buttons beside the graph.
function LayerRail({ counts, layerFilter, onLayerFilterChange, visibleCounts }) {
  return (
    <aside className="tree-layer-rail">
      <h4>Layers</h4>
      {[0, 1, 2, 3].map((layer) => {
        const active = layerFilter === String(layer);
        return (
          <button
            key={layer}
            type="button"
            className={`tree-layer-link ${active ? "active" : ""}`}
            onClick={() => onLayerFilterChange(active ? "all" : String(layer))}
          >
            <span>{formatLayerLabel(layer)}</span>
            <strong>{visibleCounts[layer] || 0} / {counts[layer] || 0}</strong>
          </button>
        );
      })}
    </aside>
  );
}

// Centralizes graph search, filtering, overlap mode, and zoom controls.
function GraphToolbar({
  query,
  onQueryChange,
  layerFilter,
  onLayerFilterChange,
  statusFilter,
  onStatusFilterChange,
  overlapMode,
  onOverlapModeChange,
  zoom,
  onZoomChange,
  focusBranch,
  onFocusBranchChange,
  onExpandAll,
  onCollapseAll,
  onResetView,
}) {
  return (
    <div className="tree-toolbar panel">
      <div className="tree-toolbar-row">
        <label className="tree-toolbar-search">
          Search
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search title, description, status"
          />
        </label>
        <label className="compact-select">
          Layer
          <select value={layerFilter} onChange={(event) => onLayerFilterChange(event.target.value)}>
            <option value="all">All layers</option>
            <option value="0">Layer 0</option>
            <option value="1">Layer 1</option>
            <option value="2">Layer 2</option>
          </select>
        </label>
        <label className="compact-select">
          Status
          <select value={statusFilter} onChange={(event) => onStatusFilterChange(event.target.value)}>
            <option value="all">All statuses</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="tree-toolbar-row">
        <div className="segmented">
          {OVERLAP_MODE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={overlapMode === option.value ? "active" : ""}
              onClick={() => onOverlapModeChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="button-row">
          <button
            type="button"
            className={focusBranch ? "secondary-button active-soft" : "secondary-button"}
            onClick={() => onFocusBranchChange(!focusBranch)}
          >
            {focusBranch ? "Show Full Map" : "Focus Branch"}
          </button>
          <button type="button" className="secondary-button" onClick={onExpandAll}>Expand All</button>
          <button type="button" className="secondary-button" onClick={onCollapseAll}>Collapse All</button>
          <button type="button" className="secondary-button" onClick={() => onZoomChange(clamp(zoom - 0.1, MIN_ZOOM, MAX_ZOOM))}>-</button>
          <button type="button" className="secondary-button" onClick={() => onZoomChange(clamp(zoom + 0.1, MIN_ZOOM, MAX_ZOOM))}>+</button>
          <button type="button" className="secondary-button" onClick={onResetView}>Reset View</button>
        </div>
      </div>
    </div>
  );
}

function TreeCanvas({
  graph,
  selectedId,
  onSelect,
  collapsedIds,
  onToggleCollapse,
  overlapMode,
  overlapEdges,
  overlapDegree,
  researchSignals,
  zoom,
  onZoomChange,
}) {
  // Renders the positioned tree cards and overlay relationships in one scrollable canvas.
  const scrollRef = useRef(null);
  const dragRef = useRef(null);

  // Starts canvas panning unless the user is interacting with a node card.
  function handleMouseDown(event) {
    const target = event.target;
    if (target?.closest?.("[data-tree-node='true']")) {
      return;
    }
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: scrollRef.current?.scrollLeft || 0,
      scrollTop: scrollRef.current?.scrollTop || 0,
    };
  }

  // Applies drag deltas to the scroll container.
  function handleMouseMove(event) {
    if (!dragRef.current || !scrollRef.current) {
      return;
    }
    const deltaX = event.clientX - dragRef.current.startX;
    const deltaY = event.clientY - dragRef.current.startY;
    scrollRef.current.scrollLeft = dragRef.current.scrollLeft - deltaX;
    scrollRef.current.scrollTop = dragRef.current.scrollTop - deltaY;
  }

  // Clears the active pan gesture.
  function stopDrag() {
    dragRef.current = null;
  }

  // Aligns the soft background layer bands with node columns.
  function layerBandX(depth) {
    return CANVAS_PADDING + depth * (NODE_WIDTH + HORIZONTAL_GAP) - 28;
  }

  const maxOverlap = Math.max(1, ...Object.values(overlapDegree));
  const selectedEdgeIds = new Set(overlapEdges.map((edge) => edge.from === selectedId ? edge.to : edge.from));

  function handleNodeKeyDown(event, nodeId) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onSelect(nodeId);
  }

  function handleCollapseKeyDown(event, nodeId) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    event.stopPropagation();
    onToggleCollapse(nodeId);
  }

  return (
    <div
      ref={scrollRef}
      className="tree-canvas-scroll"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={stopDrag}
      onMouseLeave={stopDrag}
      onWheel={(event) => {
        if (!event.ctrlKey) {
          return;
        }
        event.preventDefault();
        onZoomChange(clamp(zoom + (event.deltaY > 0 ? -0.05 : 0.05), MIN_ZOOM, MAX_ZOOM));
      }}
    >
      <div className="tree-canvas-stage" style={{ width: graph.width * zoom, height: graph.height * zoom }}>
        <svg
          width={graph.width}
          height={graph.height}
          className="tree-canvas"
          style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
          role="img"
          aria-label="Visual product map"
        >
          {[0, 1, 2, 3].filter((layer) => layer <= graph.maxDepth).map((layer) => (
            <g key={layer}>
              <rect
                x={layerBandX(layer)}
                y={24}
                width={NODE_WIDTH + 56}
                height={graph.height - 48}
                className="tree-layer-band"
                rx="28"
              />
              <text x={layerBandX(layer) + 24} y={52} className="tree-layer-band-label">
                {formatLayerLabel(graph.baseLayer + layer)}
              </text>
            </g>
          ))}
          {graph.edges.map((edge) => {
            const from = graph.byId[edge.from];
            const to = graph.byId[edge.to];
            if (!from || !to) {
              return null;
            }
            const startX = from.x + from.width;
            const startY = from.y + from.height / 2;
            const endX = to.x;
            const endY = to.y + to.height / 2;
            const controlA = startX + HORIZONTAL_GAP / 2;
            const controlB = endX - HORIZONTAL_GAP / 2;
            return (
              <path
                key={`${edge.from}-${edge.to}`}
                d={`M ${startX} ${startY} C ${controlA} ${startY}, ${controlB} ${endY}, ${endX} ${endY}`}
                className="tree-edge"
              />
            );
          })}
          {overlapEdges.map((edge) => {
            const from = graph.byId[edge.from];
            const to = graph.byId[edge.to];
            if (!from || !to) {
              return null;
            }
            const startX = from.x + from.width / 2;
            const startY = from.y + from.height / 2;
            const endX = to.x + to.width / 2;
            const endY = to.y + to.height / 2;
            return (
              <path
                key={edge.id}
                d={`M ${startX} ${startY} C ${startX + 42} ${startY}, ${endX - 42} ${endY}, ${endX} ${endY}`}
                className={`tree-edge overlap ${edge.type}`}
              />
            );
          })}
          {graph.nodes.map((node) => {
            const overlapCount = overlapDegree[node.id] || 0;
            const isSelected = node.id === selectedId;
            const isRelated = selectedEdgeIds.has(node.id);
            const heatLevel = overlapMode === "heatmap" && overlapCount
              ? clamp(Math.round((overlapCount / maxOverlap) * 4), 1, 4)
              : 0;
            return (
              <g
                key={node.id}
                transform={`translate(${node.x}, ${node.y})`}
                className={[
                  "tree-node",
                  nodeTone(node),
                  isSelected ? "selected" : "",
                  isRelated ? "related" : "",
                  heatLevel ? `heat-${heatLevel}` : "",
                ].filter(Boolean).join(" ")}
                onClick={() => onSelect(node.id)}
                onKeyDown={(event) => handleNodeKeyDown(event, node.id)}
                role="button"
                tabIndex={0}
                aria-label={`${node.title}, ${formatLayerLabel(node.layer)}, ${node.status}. Select node.`}
                aria-pressed={isSelected}
                data-tree-node="true"
              >
                <rect rx="18" ry="18" width={node.width} height={node.height} className="tree-node-box" data-tree-node="true" />
                <foreignObject x="18" y="14" width={node.width - 36} height={node.height - 26} data-tree-node="true">
                  <div className="tree-node-content" data-tree-node="true">
                    <div className="tree-node-kicker" data-tree-node="true">
                      {formatLayerLabel(node.layer)} | {formatNodeType(node.node_type)}
                    </div>
                    <div className="tree-node-title" data-tree-node="true">{node.title}</div>
                    <div className="tree-node-description" data-tree-node="true">{node.description || "No description yet."}</div>
                    <div className="tree-node-status" data-tree-node="true">{node.status}</div>
                    <div className="tree-node-status subtle" data-tree-node="true">
                      {node.child_count ? `${node.child_count} branches` : "Leaf node"}
                      {overlapCount ? ` | ${overlapCount} overlaps` : ""}
                      {researchSignals[node.id] ? " | research stale" : ""}
                    </div>
                  </div>
                </foreignObject>
                {node.hasChildren ? (
                  <g
                    transform={`translate(${node.width - 38}, 14)`}
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleCollapse(node.id);
                    }}
                    onKeyDown={(event) => handleCollapseKeyDown(event, node.id)}
                    className="tree-collapse-control"
                    role="button"
                    tabIndex={0}
                    aria-label={`${collapsedIds.has(node.id) ? "Expand" : "Collapse"} ${node.title}`}
                    aria-expanded={!collapsedIds.has(node.id)}
                    data-tree-node="true"
                  >
                    <circle r="12" cx="0" cy="0" />
                    <text x="-4" y="5">{collapsedIds.has(node.id) ? "+" : "-"}</text>
                  </g>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function MapOutline({
  nodes,
  selectedId,
  collapsedIds,
  overlapDegree,
  researchSignals,
  onSelect,
  onToggleCollapse,
}) {
  if (!nodes.length) {
    return (
      <div className="tree-map-outline empty">
        <p className="muted">No map entities match the current filters.</p>
      </div>
    );
  }

  return (
    <nav className="tree-map-outline" aria-label="Accessible product map outline">
      <div className="tree-map-outline-header">
        <strong>Map outline</strong>
        <span className="muted">{nodes.length} visible</span>
      </div>
      <ul>
        {nodes.map((node) => {
          const isSelected = node.id === selectedId;
          const isCollapsed = collapsedIds.has(node.id);
          const overlapCount = overlapDegree[node.id] || 0;
          return (
            <li key={node.id} style={{ "--node-depth": Math.max(0, node.layer || 0) }}>
              <div className={isSelected ? "tree-outline-row selected" : "tree-outline-row"}>
                <button
                  type="button"
                  className="tree-outline-main"
                  onClick={() => onSelect(node.id)}
                  aria-current={isSelected ? "true" : undefined}
                >
                  <span className="tree-outline-meta">{formatLayerLabel(node.layer)} | {formatNodeType(node.node_type)}</span>
                  <strong>{node.title}</strong>
                  <span>{node.status}{overlapCount ? ` | ${overlapCount} overlaps` : ""}{researchSignals[node.id] ? " | research stale" : ""}</span>
                </button>
                {node.hasChildren ? (
                  <button
                    type="button"
                    className="tree-outline-toggle"
                    onClick={() => onToggleCollapse(node.id)}
                    aria-expanded={!isCollapsed}
                    aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${node.title}`}
                  >
                    {isCollapsed ? "+" : "-"}
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

// Displays the published Layer 0 brief values in the detail drawer.
function Layer0Detail({ brief }) {
  const rows = [
    { label: "Known Competitors", value: (brief?.known_competitors || []).join(", ") || "None entered" },
    { label: "Target Users", value: brief?.target_users || "Not set" },
    { label: "Constraints", value: brief?.constraints || "Not set" },
    { label: "Goals", value: (brief?.goals || []).join(", ") || "Not set" },
    { label: "Preferred Directions", value: (brief?.preferred_directions || []).join(", ") || "Not set" },
    { label: "Rejected Directions", value: (brief?.rejected_directions || []).join(", ") || "Not set" },
  ];

  return (
    <>
      <div className="tree-detail-grid">
        {rows.map((row) => (
          <div key={row.label} className="tree-detail-row">
            <span>{row.label}</span>
            <strong>{row.value}</strong>
          </div>
        ))}
      </div>
      {brief?.notes ? (
        <div className="tree-detail-section">
          <h4>Notes</h4>
          <p>{brief.notes}</p>
        </div>
      ) : null}
    </>
  );
}

// Shows Layer 1 research evidence when the selected node is a pillar.
function PillarResearch({ node, findings }) {
  if (node.layer !== 1 || node.node_type !== "pillar") {
    return null;
  }
  const finding = findings.find(
    (item) => item.scope === "layer1" && item.scope_id === node.id && item.finding_type === "pillar_coverage_matrix",
  );
  const matrix = finding?.payload?.matrix || [];
  const profile = finding?.payload?.engineering_profile || null;
  if (!matrix.length && !profile) {
    return null;
  }
  return (
    <div className="tree-detail-section layer1-research-section">
      <div className="layer1-section-heading">
        <div>
          <h4>Research evidence</h4>
          <p className="muted">Competitor and implementation signals for this pillar.</p>
        </div>
        {matrix.length ? <span className="status-pill">{matrix.length} competitors</span> : null}
      </div>
      {profile ? (
        <div className="research-scorecard">
          <div className="research-scorecard-head">
            <strong>Implementation profile</strong>
            <div className="research-scorecard-head-meta">
              <span className="status-pill">confidence {profile.confidence}/100</span>
              <span className="research-index-pill">indexed score {profile.indexed_score ?? 0}/100</span>
            </div>
          </div>
          <p className="research-scorecard-summary">{profile.summary}</p>
          <div className="research-rating-grid">
            {(profile.ratings || []).map((rating) => (
              <div key={rating.name} className="research-rating-card">
                <span>{rating.label}</span>
                <strong>{rating.rating}/10</strong>
                <p>{rating.rationale}</p>
              </div>
            ))}
          </div>
          {profile.implications?.length ? (
            <ul className="summary-list">
              {profile.implications.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <ul className="summary-list layer1-competitor-list">
        {matrix.slice(0, 5).map((row) => (
          <li key={row.competitor_name}>
            <strong>{row.competitor_name}</strong>
            <span>{row.coverage_status} | {row.adoption_level} | confidence {row.confidence}</span>
            {row.evidence?.[0]?.url ? (
              <>
                {" "}
                <a href={row.evidence[0].url} target="_blank" rel="noreferrer">source</a>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Layer1PillarForm({ disabled, onCreate }) {
  const [form, setForm] = useState({ title: "", description: "", status: "kept", priority: 0 });
  const [saveState, setSaveState] = useState("idle");

  async function submit(event) {
    event.preventDefault();
    if (!onCreate || disabled || !form.title.trim()) {
      return;
    }
    setSaveState("saving");
    try {
      await onCreate({
        ...form,
        title: form.title.trim(),
        description: form.description.trim(),
        priority: Number(form.priority || 0),
      });
      setForm({ title: "", description: "", status: "kept", priority: 0 });
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }

  return (
    <form className="tree-edit-form layer1-pillar-form" onSubmit={submit}>
      <div className="panel-header">
        <div>
          <h4>Manual Layer 1 pillar</h4>
          <p className="muted">{disabled ? "Publish the Layer 0 brief before adding pillars." : "Add a known high-level product area without running generation."}</p>
        </div>
        <div className={`tree-save-state ${saveState !== "idle" ? saveState : ""}`} aria-live="polite">{saveState === "saving" ? "Saving..." : saveState === "saved" ? "Saved" : saveState === "error" ? "Could not save" : ""}</div>
      </div>
      <label>
        Pillar title
        <input disabled={disabled} value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} />
      </label>
      <label>
        Description
        <textarea disabled={disabled} rows={4} value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} />
      </label>
      <div className="field-row">
        <label>
          Status
          <select disabled={disabled} value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value }))}>
            {["kept", "prioritized", "generated"].map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Priority
          <input disabled={disabled} type="number" min="0" max="10" value={form.priority} onChange={(event) => setForm((current) => ({ ...current, priority: Number(event.target.value) }))} />
        </label>
      </div>
      <button type="submit" disabled={disabled || !form.title.trim()}>Add pillar</button>
    </form>
  );
}

function BriefInspector({ brief, onSaveBrief, onPublishBrief, onCreatePillar, onGenerateLayer1, generationControls, locked, onUnlockLayer0 }) {
  const [form, setForm] = useState(brief || {});

  useEffect(() => setForm(brief || {}), [brief]);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  return (
    <div className="tree-edit-form">
      {locked ? (
        <div className="status-banner">
          <strong>Layer 0 is locked.</strong> Unlock only if the product plan has changed enough to review downstream layers again.
        </div>
      ) : null}
      <label>Product idea<textarea disabled={locked} rows={5} value={form.product_idea || ""} onChange={(event) => update("product_idea", event.target.value)} /></label>
      <label>Target users<textarea disabled={locked} rows={3} value={form.target_users || ""} onChange={(event) => update("target_users", event.target.value)} /></label>
      <label>Constraints<textarea disabled={locked} rows={3} value={form.constraints || ""} onChange={(event) => update("constraints", event.target.value)} /></label>
      <label>Known competitors<textarea disabled={locked} rows={3} value={(form.known_competitors || []).join("\n")} onChange={(event) => update("known_competitors", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} /></label>
      <label>Goals<textarea disabled={locked} rows={3} value={(form.goals || []).join("\n")} onChange={(event) => update("goals", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} /></label>
      <label>Preferred directions<textarea disabled={locked} rows={3} value={(form.preferred_directions || []).join("\n")} onChange={(event) => update("preferred_directions", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} /></label>
      <label>Rejected directions<textarea disabled={locked} rows={3} value={(form.rejected_directions || []).join("\n")} onChange={(event) => update("rejected_directions", event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} /></label>
      <label>Notes<textarea disabled={locked} rows={4} value={form.notes || ""} onChange={(event) => update("notes", event.target.value)} /></label>
      <div className="button-row">
        {locked ? <button type="button" onClick={onUnlockLayer0}>Unlock Layer 0</button> : <button type="button" onClick={() => onSaveBrief?.(form)}>Save brief</button>}
        {brief?.status !== "published" ? <button type="button" className="secondary-button" onClick={onPublishBrief}>Publish</button> : null}
        <button type="button" disabled={brief?.status !== "published"} onClick={onGenerateLayer1}>Broaden Layer 1</button>
      </div>
      <details className="review-details">
        <summary>Advanced generation controls</summary>
        <div className="brief-grid">
          <label>Thinking<input type="checkbox" checked={generationControls.layer1Thinking} onChange={(event) => generationControls.setLayer1Thinking(event.target.checked)} /></label>
          <label>Max rounds<input type="number" value={generationControls.layer1MaxRounds} onChange={(event) => generationControls.setLayer1MaxRounds(Number(event.target.value))} /></label>
          <label>Target per round<input type="number" value={generationControls.layer1TargetPerRound} onChange={(event) => generationControls.setLayer1TargetPerRound(Number(event.target.value))} /></label>
          <label>Total cap<input type="number" min="1" placeholder="No cap" value={generationControls.layer1TotalCap ?? ""} onChange={(event) => generationControls.setLayer1TotalCap(event.target.value)} /></label>
          <label>Min new<input type="number" value={generationControls.layer1MinNew} onChange={(event) => generationControls.setLayer1MinNew(Number(event.target.value))} /></label>
        </div>
      </details>
      <Layer1PillarForm disabled={brief?.status !== "published"} onCreate={onCreatePillar} />
    </div>
  );
}

export function NodeDetail({
  node,
  brief,
  findings,
  parentNode,
  childNodes,
  overlapLinks,
  onSelectNode,
  onSaveNode,
  onCreatePillar,
  pillars,
  onSaveBrief,
  onPublishBrief,
  onUpdateFeature,
  onCreateFeature,
  onReviewFeature,
  onAddEvidence,
  onResearchLayer1,
  onResearchLayer2,
  onGenerateLayer1,
  onGenerateLayer2,
  generationControls,
  layer0Locked,
  onUnlockLayer0,
}) {
  // Detail drawer for reviewing and lightly editing the selected tree node.
  const [title, setTitle] = useState(node?.title || "");
  const [description, setDescription] = useState(node?.description || "");
  const [status, setStatus] = useState(node?.status || "generated");
  const [priority, setPriority] = useState(node?.priority ?? 0);
  const [saveState, setSaveState] = useState("idle");

  useEffect(() => {
    setTitle(node?.title || "");
    setDescription(node?.description || "");
    setStatus(node?.status || "generated");
    setPriority(node?.priority ?? 0);
    setSaveState("idle");
  }, [node?.id, node?.title, node?.description, node?.status, node?.priority]);

  if (!node) {
    return (
      <section className="tree-detail">
        <p className="muted">Select a node to inspect it.</p>
      </section>
    );
  }

  if (node.entity_type === "feature") {
    return (
      <section className="tree-detail">
        <FeatureDetail
          feature={node.json_payload}
          pillars={pillars}
          onUpdate={onUpdateFeature}
          onReview={onReviewFeature}
          onAddEvidence={onAddEvidence}
        />
        <div className="button-row">
          {onResearchLayer2 ? <button type="button" className="secondary-button" onClick={() => onResearchLayer2([node.id])}>Research Feature</button> : null}
          {parentNode ? <button type="button" className="link-button" onClick={() => onSelectNode(parentNode.id)}>Back to {parentNode.title}</button> : null}
        </div>
      </section>
    );
  }

  // Persists edits for generated nodes while keeping Layer 0 read-only here.
  async function commitEdit(next) {
    if (!onSaveNode || node.layer === 0) {
      return;
    }
    setSaveState("saving");
    try {
      await onSaveNode(node.id, next);
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }

  const detailRows = detailRowsForNode(node, parentNode);
  const isLayer1Pillar = node.layer === 1 && node.node_type === "pillar";
  const pillarReadyForLayer2 = isLayer1Pillar && ["kept", "prioritized"].includes(node.status);

  return (
    <section className="tree-detail">
      <div className="tree-detail-header">
        <div>
          <span className={`status-pill ${node.status}`}>{formatLayerLabel(node.layer)}</span>
          <h3>{node.title}</h3>
          <p>{node.description || "No description yet."}</p>
        </div>
        <div className="tree-save-state">{saveState === "saving" ? "Saving..." : saveState === "saved" ? "Saved" : ""}</div>
      </div>

      {node.layer === 0 ? (
        <>
          <Layer0Detail brief={brief} />
          <BriefInspector
            brief={brief}
            onSaveBrief={onSaveBrief}
            onPublishBrief={onPublishBrief}
            onCreatePillar={onCreatePillar}
            onGenerateLayer1={onGenerateLayer1}
            generationControls={generationControls}
            locked={layer0Locked}
            onUnlockLayer0={onUnlockLayer0}
          />
        </>
      ) : (
        <>
          <div className="tree-action-strip">
            <button type="button" className="secondary-button" onClick={() => { setStatus("kept"); commitEdit({ title, description, status: "kept", priority }); }}>Accept</button>
            <button type="button" className="secondary-button" onClick={() => { setStatus("cut"); commitEdit({ title, description, status: "cut", priority }); }}>Reject</button>
            <button type="button" className="secondary-button" onClick={() => { setStatus("merged"); commitEdit({ title, description, status: "merged", priority }); }}>Merge</button>
            <button type="button" className="secondary-button" onClick={() => { setStatus("prioritized"); commitEdit({ title, description, status: "prioritized", priority }); }}>Prioritize</button>
          </div>

          <div className="tree-detail-grid">
            {detailRows.map((row) => (
              <div key={row.label} className="tree-detail-row">
                <span>{row.label}</span>
                <strong>{row.value}</strong>
              </div>
            ))}
          </div>

          {isLayer1Pillar ? (
            <div className={pillarReadyForLayer2 ? "layer1-next-step ready" : "layer1-next-step"}>
              <div>
                <strong>{pillarReadyForLayer2 ? "Ready for Layer 2 expansion" : "Review this pillar before expansion"}</strong>
                <p className="muted">
                  {pillarReadyForLayer2
                    ? "Expand this pillar into concrete Layer 2 capabilities, or research it first if competitive evidence matters."
                    : "Keep or prioritize the pillar when it belongs in the product tree. Cut or merge it if the scope is weak or duplicated."}
                </p>
              </div>
              <span className={`status-pill ${node.status}`}>{node.status}</span>
            </div>
          ) : null}

          <div className="tree-edit-form">
            <label>
              Title
              <input value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <div className="field-row">
              <label>
                Status
                <select value={status} onChange={(event) => setStatus(event.target.value)}>
                  {STATUS_OPTIONS.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </label>
              <label>
                Priority
                <input
                  type="number"
                  min="0"
                  max="10"
                  value={priority}
                  onChange={(event) => setPriority(Number(event.target.value))}
                />
              </label>
            </div>
            <label>
              Description
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={7} />
            </label>
            <div className="button-row">
              <button type="button" onClick={() => commitEdit({ title, description, status, priority })}>Save {isLayer1Pillar ? "pillar" : "node"}</button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setTitle(node.title || "");
                  setDescription(node.description || "");
                  setStatus(node.status || "generated");
                  setPriority(node.priority ?? 0);
                }}
              >
                Reset
              </button>
            </div>
          </div>
          {node.layer === 1 && ["kept", "prioritized"].includes(node.status) ? (
            <>
              <div className="button-row layer1-action-row">
                <button type="button" onClick={() => onGenerateLayer2?.([node.id])}>Expand this pillar</button>
                {onResearchLayer1 ? <button type="button" className="secondary-button" onClick={() => onResearchLayer1([node.id])}>Research pillar</button> : null}
                <Layer2FeatureForm pillars={pillars} defaultOwnerId={node.id} onCreate={onCreateFeature} />
              </div>
              <details className="review-details">
                <summary>Advanced generation controls</summary>
                <div className="brief-grid">
                  <label>Thinking<input type="checkbox" checked={generationControls.layer2Thinking} onChange={(event) => generationControls.setLayer2Thinking(event.target.checked)} /></label>
                  <label>Max rounds<input type="number" value={generationControls.layer2MaxRounds} onChange={(event) => generationControls.setLayer2MaxRounds(Number(event.target.value))} /></label>
                  <label>Target per round<input type="number" value={generationControls.layer2TargetPerRound} onChange={(event) => generationControls.setLayer2TargetPerRound(Number(event.target.value))} /></label>
                  <label>Total cap<input type="number" min="1" placeholder="No cap" value={generationControls.layer2TotalCap ?? ""} onChange={(event) => generationControls.setLayer2TotalCap(event.target.value)} /></label>
                  <label>Min new<input type="number" value={generationControls.layer2MinNew} onChange={(event) => generationControls.setLayer2MinNew(Number(event.target.value))} /></label>
                </div>
              </details>
            </>
          ) : null}
        </>
      )}

      {parentNode ? (
        <div className="tree-detail-section">
          <h4>Parent Context</h4>
          <button type="button" className="link-button" onClick={() => onSelectNode(parentNode.id)}>
            {parentNode.title}
          </button>
        </div>
      ) : null}

      {childNodes.length ? (
        <div className="tree-detail-section">
          <h4>Child Branches</h4>
          <div className="tree-chip-list">
            {childNodes.map((child) => (
              <button key={child.id} type="button" className="tree-chip" onClick={() => onSelectNode(child.id)}>
                {child.title}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {overlapLinks.length ? (
        <div className="tree-detail-section">
          <h4>Overlap Signals</h4>
          <ul className="summary-list">
            {overlapLinks.map((link) => (
              <li key={link.id}>
                <button type="button" className="link-button" onClick={() => onSelectNode(link.target.id)}>
                  {link.target.title}
                </button>
                {" "} | {link.type.replaceAll("_", " ")} | {link.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <PillarResearch node={node} findings={findings} />
    </section>
  );
}


export { DashboardStats, GraphToolbar, LayerRail, MapOutline, TreeCanvas };
