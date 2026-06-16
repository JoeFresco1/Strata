import { useEffect, useMemo, useRef, useState } from "react";

const NODE_WIDTH = 280;
const NODE_HEIGHT = 132;
const HORIZONTAL_GAP = 156;
const VERTICAL_GAP = 54;
const CANVAS_PADDING = 56;
const CANVAS_TOP_PADDING = 92;
const MIN_ZOOM = 0.7;
const MAX_ZOOM = 1.7;
const STATUS_OPTIONS = ["generated", "kept", "cut", "merged", "prioritized", "draft", "published"];
const OVERLAP_MODE_OPTIONS = [
  { value: "focus", label: "Focus" },
  { value: "heatmap", label: "Heatmap" },
  { value: "overlap", label: "Overlap View" },
];

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function truncate(value, maxLength) {
  if (!value) {
    return "";
  }
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 3)}...`;
}

function formatLayerLabel(layer) {
  return `Layer ${layer}`;
}

function formatNodeType(value) {
  return (value || "node").replaceAll("_", " ");
}

function buildRootNode(project, brief, tree) {
  const idea = brief?.product_idea || project?.idea || "No product idea yet.";
  return {
    id: "layer0-root",
    parent_id: null,
    title: project?.name || "Untitled Project",
    description: idea,
    layer: 0,
    node_type: "brief",
    status: brief?.status || "draft",
    priority: null,
    child_count: tree?.length || 0,
    json_payload: {
      brief_summary: {
        known_competitors: brief?.known_competitors || [],
        target_users: brief?.target_users || "",
        constraints: brief?.constraints || "",
        goals: brief?.goals || [],
        preferred_directions: brief?.preferred_directions || [],
        rejected_directions: brief?.rejected_directions || [],
        notes: brief?.notes || "",
      },
    },
    children: tree || [],
  };
}

function withDerivedFields(node, parentId = null) {
  const children = (node.children || []).map((child) => withDerivedFields(child, node.id));
  return {
    ...node,
    parent_id: node.parent_id ?? parentId,
    child_count: node.child_count ?? children.length,
    children,
  };
}

function buildTreeIndex(root) {
  const byId = {};
  const parentById = {};
  const ancestorsById = {};
  const collapsibleIds = [];
  const byLayer = new Map();
  const order = [];

  function visit(node, ancestors) {
    byId[node.id] = node;
    parentById[node.id] = node.parent_id || null;
    ancestorsById[node.id] = ancestors;
    order.push(node.id);
    byLayer.set(node.layer, (byLayer.get(node.layer) || 0) + 1);
    if (node.children?.length) {
      collapsibleIds.push(node.id);
    }
    (node.children || []).forEach((child) => visit(child, [...ancestors, node.id]));
  }

  visit(root, []);
  return { byId, parentById, ancestorsById, collapsibleIds, byLayer, order };
}

function createInitialCollapsedSet(root) {
  const collapsed = new Set();

  function visit(node) {
    if (node.layer >= 1 && node.children?.length) {
      collapsed.add(node.id);
    }
    (node.children || []).forEach(visit);
  }

  visit(root);
  return collapsed;
}

function collectOverlapEdges(root) {
  const index = buildTreeIndex(root);
  const edges = [];
  const degree = {};
  const researchByNode = {};
  const seen = new Set();

  function addEdge(sourceId, targetId, type, detail, score = 0) {
    if (!index.byId[sourceId] || !index.byId[targetId] || sourceId === targetId) {
      return;
    }
    const pair = [sourceId, targetId].sort().join("|");
    const key = `${type}|${pair}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    edges.push({
      id: key,
      from: sourceId,
      to: targetId,
      type,
      detail,
      score,
    });
    degree[sourceId] = (degree[sourceId] || 0) + 1;
    degree[targetId] = (degree[targetId] || 0) + 1;
  }

  Object.values(index.byId).forEach((node) => {
    const duplicate = node.json_payload?.possible_duplicate;
    if (duplicate?.duplicate_node_id) {
      addEdge(
        node.id,
        duplicate.duplicate_node_id,
        "possible_duplicate",
        `Title ${duplicate.title_score} | description ${duplicate.description_score}`,
        Number(duplicate.title_score || 0),
      );
    }
    const semanticMatches = node.json_payload?.semantic_similarity?.matches || [];
    semanticMatches.forEach((match) => {
      addEdge(node.id, match.node_id, "semantic_similarity", `Cosine similarity ${match.score}`, Number(match.score || 0));
    });
    if (node.layer === 1 && node.node_type === "pillar") {
      const stale = node.json_payload?.research_stale;
      if (stale) {
        researchByNode[node.id] = stale.reason || "Research stale";
      }
    }
  });

  return { edges, degree, researchByNode };
}

function matchesFilters(node, filters) {
  const query = filters.query.trim().toLowerCase();
  const searchableText = [node.title, node.description, node.node_type, node.status].filter(Boolean).join(" ").toLowerCase();
  const queryMatch = !query || searchableText.includes(query);
  const layerMatch = filters.layerFilter === "all" || String(node.layer) === filters.layerFilter;
  const statusMatch = filters.statusFilter === "all" || node.status === filters.statusFilter;
  return queryMatch && layerMatch && statusMatch;
}

function filterTree(node, filters) {
  const children = (node.children || [])
    .map((child) => filterTree(child, filters))
    .filter(Boolean);
  const includeSelf = node.layer === 0 || matchesFilters(node, filters);
  if (!includeSelf && !children.length) {
    return null;
  }
  return { ...node, child_count: node.child_count ?? children.length, children };
}

function collectVisibleIds(root) {
  const ids = new Set();
  function visit(node) {
    ids.add(node.id);
    (node.children || []).forEach(visit);
  }
  visit(root);
  return ids;
}

function buildVisibleGraph(root, collapsedIds) {
  const nodes = [];
  const edges = [];
  const byId = {};
  let maxDepth = 0;
  let nextLeafY = CANVAS_TOP_PADDING;

  function place(node, depth, parentId = null) {
    const visibleChildren = collapsedIds.has(node.id) ? [] : node.children || [];
    const placedChildren = visibleChildren.map((child) => place(child, depth + 1, node.id));
    const y = placedChildren.length
      ? placedChildren.length === 1
        ? placedChildren[0].y
        : (placedChildren[0].y + placedChildren[placedChildren.length - 1].y) / 2
      : nextLeafY;

    if (!placedChildren.length) {
      nextLeafY += NODE_HEIGHT + VERTICAL_GAP;
    }

    const x = CANVAS_PADDING + depth * (NODE_WIDTH + HORIZONTAL_GAP);
    const graphNode = {
      ...node,
      x,
      y,
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      hasChildren: Boolean(node.child_count || node.children?.length),
      visibleChildCount: placedChildren.length,
    };
    nodes.push(graphNode);
    byId[node.id] = graphNode;
    maxDepth = Math.max(maxDepth, depth);
    if (parentId) {
      edges.push({ from: parentId, to: node.id });
    }
    return graphNode;
  }

  place(root, 0);
  nodes.sort((left, right) => left.y - right.y || left.layer - right.layer);

  return {
    nodes,
    edges,
    byId,
    maxDepth,
    width: CANVAS_PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * HORIZONTAL_GAP,
    height: Math.max(520, nextLeafY + CANVAS_PADDING),
  };
}

function nodeTone(node) {
  if (node.layer === 0) {
    return "layer0";
  }
  if (node.status === "prioritized") {
    return "prioritized";
  }
  if (node.status === "kept") {
    return "kept";
  }
  if (node.status === "cut") {
    return "cut";
  }
  if (node.status === "merged") {
    return "merged";
  }
  if (node.node_type === "spec") {
    return "spec";
  }
  if (node.node_type === "subfeature") {
    return "subfeature";
  }
  return "pillar";
}

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
  const scrollRef = useRef(null);
  const dragRef = useRef(null);

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

  function handleMouseMove(event) {
    if (!dragRef.current || !scrollRef.current) {
      return;
    }
    const deltaX = event.clientX - dragRef.current.startX;
    const deltaY = event.clientY - dragRef.current.startY;
    scrollRef.current.scrollLeft = dragRef.current.scrollLeft - deltaX;
    scrollRef.current.scrollTop = dragRef.current.scrollTop - deltaY;
  }

  function stopDrag() {
    dragRef.current = null;
  }

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

function detailRowsForNode(node, parentNode) {
  if (!node) {
    return [];
  }
  return [
    { label: "Type", value: formatNodeType(node.node_type) },
    { label: "Layer", value: formatLayerLabel(node.layer) },
    { label: "Status", value: node.status },
    { label: "Priority", value: node.priority ?? "Not set" },
    { label: "Parent", value: parentNode?.title || "Root" },
    { label: "Children", value: String(node.child_count || 0) },
  ];
}

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

function PillarResearch({ node, findings }) {
  if (node.layer !== 1 || node.node_type !== "pillar") {
    return null;
  }
  const finding = findings.find(
    (item) => item.scope === "layer1" && item.scope_id === node.id && item.finding_type === "pillar_coverage_matrix",
  );
  const matrix = finding?.payload?.matrix || [];
  if (!matrix.length) {
    return null;
  }
  return (
    <div className="tree-detail-section">
      <h4>Research Evidence</h4>
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

  function collapseAll() {
    setCollapsedIds(new Set(fullIndex.collapsibleIds.filter((nodeId) => nodeId !== root.id)));
  }

  function expandAll() {
    setCollapsedIds(new Set());
  }

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
