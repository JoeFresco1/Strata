import "./treeDashboard.css";
import { useEffect, useMemo, useRef, useState } from "react";
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
  truncate,
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
        <span>Tree Depth</span>
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
            <option value="3">Layer 3</option>
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
                {formatLayerLabel(layer)}
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
                data-tree-node="true"
              >
                <rect rx="18" ry="18" width={node.width} height={node.height} className="tree-node-box" data-tree-node="true" />
                <text x="18" y="24" className="tree-node-kicker" data-tree-node="true">
                  {formatLayerLabel(node.layer)} | {formatNodeType(node.node_type)}
                </text>
                <text x="18" y="48" className="tree-node-title" data-tree-node="true">
                  {truncate(node.title, 32)}
                </text>
                <text x="18" y="72" className="tree-node-description" data-tree-node="true">
                  {truncate(node.description || "No description yet.", 56)}
                </text>
                <text x="18" y="96" className="tree-node-status" data-tree-node="true">
                  {node.status}
                </text>
                <text x="18" y="116" className="tree-node-status subtle" data-tree-node="true">
                  {node.child_count ? `${node.child_count} branches` : "Leaf node"}
                  {overlapCount ? ` | ${overlapCount} overlaps` : ""}
                  {researchSignals[node.id] ? " | research stale" : ""}
                </text>
                {node.hasChildren ? (
                  <g
                    transform={`translate(${node.width - 38}, 14)`}
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleCollapse(node.id);
                    }}
                    className="tree-collapse-control"
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
    <div className="tree-detail-section">
      <h4>Research Evidence</h4>
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
      <ul className="summary-list">
        {matrix.slice(0, 5).map((row) => (
          <li key={row.competitor_name}>
            <strong>{row.competitor_name}</strong> | {row.coverage_status} | {row.adoption_level} | confidence {row.confidence}
            {row.evidence?.[0]?.url ? (
              <>
                {" "}
                | <a href={row.evidence[0].url} target="_blank" rel="noreferrer">source</a>
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function NodeDetail({
  node,
  brief,
  findings,
  parentNode,
  childNodes,
  overlapLinks,
  onSelectNode,
  onSaveNode,
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
        <Layer0Detail brief={brief} />
      ) : (
        <>
          <div className="tree-action-strip">
            <button type="button" className="secondary-button" onClick={() => { setStatus("kept"); commitEdit({ title, description, status: "kept", priority }); }}>Keep</button>
            <button type="button" className="secondary-button" onClick={() => { setStatus("cut"); commitEdit({ title, description, status: "cut", priority }); }}>Cut</button>
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
              <button type="button" onClick={() => commitEdit({ title, description, status, priority })}>Save Node</button>
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

export default function TreeDashboard({ project, brief, tree, findings, onSaveNode }) {
  // Interactive product map with filtering, collapse state, and overlap overlays.
  const root = useMemo(() => withDerivedFields(buildRootNode(project, brief, tree)), [project, brief, tree]);
  const fullIndex = useMemo(() => buildTreeIndex(root), [root]);
  const overlapData = useMemo(() => collectOverlapEdges(root), [root]);
  const [collapsedIds, setCollapsedIds] = useState(() => createInitialCollapsedSet(root));
  const [selectedId, setSelectedId] = useState(root.id);
  const [query, setQuery] = useState("");
  const [layerFilter, setLayerFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [overlapMode, setOverlapMode] = useState("focus");
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    setCollapsedIds(createInitialCollapsedSet(root));
    setSelectedId(root.id);
    setQuery("");
    setLayerFilter("all");
    setStatusFilter("all");
    setOverlapMode("focus");
    setZoom(1);
  }, [root.id, project?.id]);

  const filteredRoot = useMemo(
    () => filterTree(root, { query, layerFilter, statusFilter }) || root,
    [root, query, layerFilter, statusFilter],
  );
  const filteredIndex = useMemo(() => buildTreeIndex(filteredRoot), [filteredRoot]);
  const graph = useMemo(() => buildVisibleGraph(filteredRoot, collapsedIds), [filteredRoot, collapsedIds]);
  const visibleIds = useMemo(() => collectVisibleIds(filteredRoot), [filteredRoot]);

  useEffect(() => {
    if (visibleIds.has(selectedId)) {
      return;
    }
    const nextId = query && filteredIndex.order.length > 1 ? filteredIndex.order[1] : filteredRoot.id;
    setSelectedId(nextId);
  }, [selectedId, visibleIds, filteredRoot.id, filteredIndex.order, query]);

  useEffect(() => {
    if (!query.trim()) {
      return;
    }
    const nextMatch = filteredIndex.order.find((id) => id !== root.id);
    if (!nextMatch) {
      return;
    }
    setSelectedId(nextMatch);
    setCollapsedIds((current) => {
      const next = new Set(current);
      (fullIndex.ancestorsById[nextMatch] || []).forEach((ancestorId) => next.delete(ancestorId));
      return next;
    });
  }, [query, filteredIndex.order, fullIndex.ancestorsById, root.id]);

  const selectedNode = graph.byId[selectedId] || graph.byId[filteredRoot.id] || null;
  const parentNode = selectedNode ? fullIndex.byId[selectedNode.parent_id] || null : null;
  const childNodes = selectedNode ? (selectedNode.children || []) : [];

  const visibleOverlapEdges = useMemo(() => {
    const candidates = overlapData.edges.filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to));
    if (overlapMode === "overlap") {
      return candidates;
    }
    if (overlapMode === "focus" && selectedNode) {
      return candidates.filter((edge) => edge.from === selectedNode.id || edge.to === selectedNode.id);
    }
    return [];
  }, [overlapData.edges, visibleIds, overlapMode, selectedNode]);

  const visibleOverlapDegree = useMemo(() => {
    const degree = {};
    overlapData.edges
      .filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to))
      .forEach((edge) => {
        degree[edge.from] = (degree[edge.from] || 0) + 1;
        degree[edge.to] = (degree[edge.to] || 0) + 1;
      });
    return degree;
  }, [overlapData.edges, visibleIds]);

  const overlapLinks = useMemo(() => {
    if (!selectedNode) {
      return [];
    }
    return overlapData.edges
      .filter((edge) => edge.from === selectedNode.id || edge.to === selectedNode.id)
      .map((edge) => ({
        ...edge,
        target: fullIndex.byId[edge.from === selectedNode.id ? edge.to : edge.from],
      }))
      .filter((edge) => edge.target);
  }, [selectedNode, overlapData.edges, fullIndex.byId]);

  const stats = useMemo(() => {
    const visibleLayerCounts = {};
    graph.nodes.forEach((node) => {
      visibleLayerCounts[node.layer] = (visibleLayerCounts[node.layer] || 0) + 1;
    });
    const fullDepth = Math.max(...Array.from(fullIndex.byLayer.keys(), (layer) => Number(layer)), 0) + 1;
    return {
      totalNodes: fullIndex.order.length,
      visibleNodes: graph.nodes.length,
      overlapEdges: overlapData.edges.filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to)).length,
      depth: fullDepth,
      perLayer: {
        0: fullIndex.byLayer.get(0) || 0,
        1: fullIndex.byLayer.get(1) || 0,
        2: fullIndex.byLayer.get(2) || 0,
        3: fullIndex.byLayer.get(3) || 0,
      },
      visiblePerLayer: visibleLayerCounts,
    };
  }, [fullIndex, graph.nodes, graph.maxDepth, overlapData.edges, visibleIds]);

  // Toggles expansion for a single tree node.
  function toggleCollapse(nodeId) {
    setCollapsedIds((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }

  // Collapses every branch below the root.
  function collapseAll() {
    setCollapsedIds(new Set(fullIndex.collapsibleIds.filter((nodeId) => nodeId !== root.id)));
  }

  // Expands every visible branch.
  function expandAll() {
    setCollapsedIds(new Set());
  }

  // Restores the default graph zoom.
  function resetView() {
    setZoom(1);
  }

  return (
    <section className="tree-dashboard">
      <div className="panel tree-dashboard-header">
        <div>
          <h3>Product Map Dashboard</h3>
          <p className="muted">
            Layer 0 anchors the map. Browse with progressive reveal, switch overlap modes when you need denser analysis,
            and use the detail panel for lightweight structural edits without leaving the dashboard.
          </p>
        </div>
      </div>

      <GraphToolbar
        query={query}
        onQueryChange={setQuery}
        layerFilter={layerFilter}
        onLayerFilterChange={setLayerFilter}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        overlapMode={overlapMode}
        onOverlapModeChange={setOverlapMode}
        zoom={zoom}
        onZoomChange={setZoom}
        onExpandAll={expandAll}
        onCollapseAll={collapseAll}
        onResetView={resetView}
      />

      <DashboardStats stats={stats} />

      <div className="tree-workspace">
        <LayerRail
          counts={stats.perLayer}
          visibleCounts={stats.visiblePerLayer}
          layerFilter={layerFilter}
          onLayerFilterChange={setLayerFilter}
        />

        <div className="panel tree-visual-panel">
          <TreeCanvas
            graph={graph}
            selectedId={selectedNode?.id}
            onSelect={setSelectedId}
            collapsedIds={collapsedIds}
            onToggleCollapse={toggleCollapse}
            overlapMode={overlapMode}
            overlapEdges={visibleOverlapEdges}
            overlapDegree={visibleOverlapDegree}
            researchSignals={overlapData.researchByNode}
            zoom={zoom}
            onZoomChange={setZoom}
          />
        </div>

        <div className="panel tree-detail-panel">
          <NodeDetail
            node={selectedNode}
            brief={brief}
            findings={findings}
            parentNode={parentNode}
            childNodes={childNodes}
            overlapLinks={overlapLinks}
            onSelectNode={setSelectedId}
            onSaveNode={onSaveNode}
          />
        </div>
      </div>
    </section>
  );
}
