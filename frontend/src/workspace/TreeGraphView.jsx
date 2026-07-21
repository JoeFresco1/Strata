import { useEffect, useMemo, useRef, useState } from "react";
import Tree from "react-d3-tree";
import { buildTreeFromSnapshot, statusLabel } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceFilterField, WorkspaceStatusBadge } from "./WorkspacePage";

const DEFAULT_DEPTH = 2;
const DEFAULT_ZOOM = 0.82;
const COMPACT_ZOOM = 0.58;
const MIN_ZOOM = 0.35;
const MAX_ZOOM = 1.6;
const ZOOM_STEP = 0.12;

const HEATMAP_MODES = [
  { id: "none", label: "No heatmap" },
  { id: "strategic", label: "Strategic value" },
  { id: "pillarFit", label: "Pillar fit" },
  { id: "distinctiveness", label: "Distinctiveness" },
  { id: "competitorCoverage", label: "Competitor coverage" },
  { id: "implementationLeakage", label: "Implementation leakage" },
];

const LAYER_OPTIONS = [
  { id: "all", label: "All layers" },
  { id: "0", label: "L0 Product Idea" },
  { id: "1", label: "L1 Pillars" },
  { id: "2", label: "L2 Features" },
  { id: "3", label: "L3 Sub-features" },
];

function countDescendants(node) {
  return (node.children || []).reduce((total, child) => total + 1 + countDescendants(child), 0);
}

function countNodes(node) {
  return node ? 1 + (node.children || []).reduce((total, child) => total + countNodes(child), 0) : 0;
}

function graphStatusClass(status) {
  if (["kept", "prioritized", "approved", "published", "complete"].includes(status)) return "kept";
  if (["cut", "rejected", "exclude"].includes(status)) return "cut";
  if (["needs_review", "undecided", "draft", "candidate", "generated"].includes(status)) return "pending";
  if (status === "merged") return "merged";
  return "pending";
}

function nodeTabLabel(tab) {
  if (tab === "tree" || tab === "map") return "Map";
  if (tab === "layer0") return "L0 Product Idea";
  if (tab === "layer1") return "L1 Pillars";
  if (tab === "layer2") return "L2 Features";
  if (tab === "layer3") return "L3 Sub-features";
  if (tab === "export") return "Export";
  return "Workspace";
}

function scoreBand(value, heatmapMode) {
  if (heatmapMode === "none" || value === null || value === undefined) return "neutral";
  const normalized = heatmapMode === "implementationLeakage" ? 100 - value : value;
  if (normalized >= 70) return "high";
  if (normalized >= 40) return "medium";
  return "low";
}

function scoreLabel(node, heatmapMode) {
  if (heatmapMode === "none") return "";
  const value = node.scores?.[heatmapMode];
  if (value === null || value === undefined) return "No score";
  return `${Math.round(value)}/100`;
}

function formatScore(value) {
  return value === null || value === undefined ? "-" : `${Math.round(value)}/100`;
}

function formatDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function nodeMatches(node, filters) {
  const query = filters.query.trim().toLowerCase();
  const matchesQuery = !query || node.searchText?.includes(query);
  const matchesLayer = filters.layer === "all" || String(node.layer) === filters.layer;
  const matchesPillar = filters.pillar === "all" || node.id === "layer0-root" || node.pillarId === filters.pillar;
  const matchesStatus = filters.status === "all" || node.status === filters.status;
  return matchesQuery && matchesLayer && matchesPillar && matchesStatus;
}

function filterTree(node, filters) {
  if (!node) return null;
  const children = (node.children || [])
    .map((child) => filterTree(child, filters))
    .filter(Boolean);
  if (nodeMatches(node, filters) || children.length) return { ...node, children };
  return null;
}

function collectPillars(node) {
  if (!node) return [];
  const current = node.entityType === "pillar" ? [{ id: node.id, name: node.name }] : [];
  return [...current, ...(node.children || []).flatMap(collectPillars)];
}

function collectStatuses(node) {
  if (!node) return [];
  return [node.status, ...(node.children || []).flatMap(collectStatuses)].filter(Boolean);
}

export default function TreeGraphView({
  snapshot,
  onNavigate,
  onGenerateLayer1,
  onGenerateLayer2,
  onGenerateLayer3,
  onNodeSave,
  onResearchLayer0,
  onResearchLayer1,
  onResearchLayer2,
  onReviewLayer2,
  onReviewLayer3,
}) {
  const wrapperRef = useRef(null);
  const treeData = useMemo(() => buildTreeFromSnapshot(snapshot), [snapshot]);
  const [translate, setTranslate] = useState({ x: 420, y: 80 });
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [treeKey, setTreeKey] = useState(0);
  const [initialDepth, setInitialDepth] = useState(DEFAULT_DEPTH);
  const [query, setQuery] = useState("");
  const [layerFilter, setLayerFilter] = useState("all");
  const [pillarFilter, setPillarFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [heatmapMode, setHeatmapMode] = useState("none");
  const [selectedNode, setSelectedNode] = useState(null);

  const pillars = useMemo(() => collectPillars(treeData), [treeData]);
  const statuses = useMemo(() => Array.from(new Set(collectStatuses(treeData))).sort(), [treeData]);
  const filters = useMemo(() => ({
    query,
    layer: layerFilter,
    pillar: pillarFilter,
    status: statusFilter,
  }), [query, layerFilter, pillarFilter, statusFilter]);
  const filteredTree = useMemo(() => filterTree(treeData, filters) || null, [treeData, filters]);
  const activeHeatmap = HEATMAP_MODES.find((mode) => mode.id === heatmapMode) || HEATMAP_MODES[0];
  const hasFilters = Boolean(query.trim()) || layerFilter !== "all" || pillarFilter !== "all" || statusFilter !== "all";

  function defaultZoomForWidth() {
    const rect = wrapperRef.current?.getBoundingClientRect();
    return rect?.width < 760 ? COMPACT_ZOOM : DEFAULT_ZOOM;
  }

  function fitToView() {
    const rect = wrapperRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTranslate({ x: rect.width / 2, y: 84 });
    setZoom(defaultZoomForWidth());
  }

  function clearFilters() {
    setQuery("");
    setLayerFilter("all");
    setPillarFilter("all");
    setStatusFilter("all");
  }

  function resetView() {
    clearFilters();
    setHeatmapMode("none");
    setInitialDepth(DEFAULT_DEPTH);
    setTreeKey((current) => current + 1);
    window.requestAnimationFrame(fitToView);
  }

  useEffect(() => {
    fitToView();
  }, [treeData.id]);

  useEffect(() => {
    setTreeKey((current) => current + 1);
    window.requestAnimationFrame(fitToView);
  }, [query, layerFilter, pillarFilter, statusFilter]);

  function remountWithDepth(depth) {
    setInitialDepth(depth);
    setTreeKey((current) => current + 1);
    window.requestAnimationFrame(fitToView);
  }

  function changeZoom(delta) {
    setZoom((current) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Number((current + delta).toFixed(2)))));
  }

  function openInLayer(node) {
    onNavigate?.(node.tab, node.id);
  }

  async function researchNode(node) {
    if (node.entityType === "brief") return onResearchLayer0?.();
    if (node.entityType === "pillar") return onResearchLayer1?.([node.id]);
    if (node.entityType === "feature") return onResearchLayer2?.([node.id]);
    if (node.entityType === "expansion" && node.featureId) return onResearchLayer2?.([node.featureId]);
    return undefined;
  }

  async function generateChildren(node) {
    if (node.entityType === "brief") return onGenerateLayer1?.();
    if (node.entityType === "pillar") return onGenerateLayer2?.([node.id]);
    if (node.entityType === "feature") return onGenerateLayer3?.([node.id]);
    return undefined;
  }

  async function markNode(node, action) {
    if (node.entityType === "pillar") {
      const status = action === "reject" ? "cut" : action === "approve" ? "prioritized" : "kept";
      return onNodeSave?.(node.id, { status });
    }
    if (node.entityType === "feature") {
      const actionType = action === "approve" ? "approve_for_layer3" : action === "reject" ? "cut" : "keep";
      return onReviewLayer2?.({ action_type: actionType, feature_id: node.id });
    }
    if (node.entityType === "expansion") {
      const actionType = action === "reject" ? "reject" : "approve";
      return onReviewLayer3?.(node.id, actionType);
    }
    return undefined;
  }

  function renderNode({ nodeDatum, toggleNode }) {
    const childCount = countDescendants(nodeDatum);
    const collapsed = Boolean(nodeDatum.__rd3t?.collapsed);
    const canToggle = childCount > 0;
    const band = scoreBand(nodeDatum.scores?.[heatmapMode], heatmapMode);
    const scoreText = scoreLabel(nodeDatum, heatmapMode);
    const heatmapClass = heatmapMode === "none" ? "no-heatmap" : `heatmap-${band}`;
    return (
      <g>
        <foreignObject width="268" height="142" x="-134" y="-54">
          <div
            className={`tree-node-card ${graphStatusClass(nodeDatum.status)} ${heatmapClass}`}
            role="button"
            tabIndex={0}
            aria-label={`Show details for ${nodeDatum.name}`}
            title={`Show details for ${nodeDatum.name}`}
            onClick={(event) => {
              event.stopPropagation();
              setSelectedNode(nodeDatum);
            }}
            onDoubleClick={(event) => {
              event.stopPropagation();
              openInLayer(nodeDatum);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                event.stopPropagation();
                setSelectedNode(nodeDatum);
              }
            }}
          >
            <div className="tree-node-topline">
              <span className="tree-node-source">{nodeTabLabel(nodeDatum.tab)}</span>
              <span className={`tree-node-status ${graphStatusClass(nodeDatum.status)}`}>{statusLabel(nodeDatum.status || "draft")}</span>
            </div>
            <div className="tree-node-body">
              <strong>{nodeDatum.name}</strong>
            </div>
            <div className="tree-node-footer">
              {scoreText ? <span className={`tree-score-chip ${band}`}>{activeHeatmap.label}: {scoreText}</span> : <span className="tree-score-chip neutral">Status view</span>}
              {canToggle ? (
                <button
                  type="button"
                  className="tree-node-toggle"
                  aria-label={`${collapsed ? "Expand" : "Collapse"} ${nodeDatum.name}`}
                  title={`${collapsed ? "Expand" : "Collapse"} ${nodeDatum.name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    toggleNode();
                  }}
                >
                  <span>{collapsed ? "+" : "-"}</span>
                  <small>{collapsed ? `${childCount} hidden` : `${childCount} below`}</small>
                </button>
              ) : <span className="tree-leaf-label">Leaf</span>}
            </div>
          </div>
        </foreignObject>
      </g>
    );
  }

  function renderDetails() {
    if (!selectedNode) return null;
    const canResearch = ["brief", "pillar", "feature"].includes(selectedNode.entityType) || (selectedNode.entityType === "expansion" && selectedNode.featureId);
    const canGenerate = ["brief", "pillar", "feature"].includes(selectedNode.entityType);
    const canReview = ["pillar", "feature", "expansion"].includes(selectedNode.entityType);
    const canApprove = ["feature", "expansion"].includes(selectedNode.entityType);
    const canKeep = ["pillar", "feature"].includes(selectedNode.entityType);
    return (
      <aside className="workspace-inline-detail map-detail-drawer" aria-label={`${selectedNode.name} details`}>
        <div className="map-detail-heading">
          <div>
            <span className="workspace-eyebrow">{nodeTabLabel(selectedNode.tab)}</span>
            <h4>{selectedNode.name}</h4>
            <p className="muted">{selectedNode.breadcrumb?.join(" / ")}</p>
          </div>
          <WorkspaceStatusBadge status={selectedNode.status || "draft"} />
        </div>
        <div className="map-detail-copy map-detail-description">
          <strong>Description</strong>
          <p className="muted">{selectedNode.description || "No description has been captured for this item yet."}</p>
        </div>
        <dl className="map-detail-grid">
          <div><dt>Layer</dt><dd>{selectedNode.layerLabel || `L${selectedNode.layer}`}</dd></div>
          <div><dt>Parent</dt><dd>{selectedNode.parentName || "-"}</dd></div>
          <div><dt>Pillar</dt><dd>{selectedNode.pillarName || "-"}</dd></div>
          <div><dt>Child count</dt><dd>{countDescendants(selectedNode)}</dd></div>
          <div><dt>Fit score</dt><dd>{formatScore(selectedNode.scores?.pillarFit)}</dd></div>
          <div><dt>Research score</dt><dd>{formatScore(selectedNode.scores?.competitorCoverage)}</dd></div>
          <div><dt>Last updated</dt><dd>{formatDate(selectedNode.updatedAt)}</dd></div>
        </dl>
        <div className="map-detail-copy">
          <strong>Review info</strong>
          <p className="muted">{selectedNode.reviewInfo || "No review notes or score rationale are available yet."}</p>
        </div>
        <div className="map-detail-actions">
          <WorkspaceActionButton primary onClick={() => openInLayer(selectedNode)}>Open in layer</WorkspaceActionButton>
          <WorkspaceActionButton secondary onClick={() => openInLayer(selectedNode)}>Edit</WorkspaceActionButton>
          <WorkspaceActionButton secondary onClick={() => researchNode(selectedNode)} disabled={!canResearch} disabledReason={!canResearch ? "Research is not available for this item." : ""}>Research</WorkspaceActionButton>
          <WorkspaceActionButton secondary onClick={() => generateChildren(selectedNode)} disabled={!canGenerate} disabledReason={!canGenerate ? "This item does not generate children." : ""}>Generate children</WorkspaceActionButton>
          {canApprove ? <WorkspaceActionButton secondary onClick={() => markNode(selectedNode, "approve")}>Mark approved</WorkspaceActionButton> : null}
          {canKeep ? <WorkspaceActionButton secondary onClick={() => markNode(selectedNode, "keep")}>Keep</WorkspaceActionButton> : null}
          {canReview ? <WorkspaceActionButton secondary destructive onClick={() => markNode(selectedNode, "reject")}>Reject</WorkspaceActionButton> : null}
          <WorkspaceActionButton secondary onClick={() => setSelectedNode(null)}>Close</WorkspaceActionButton>
        </div>
      </aside>
    );
  }

  return (
    <WorkspacePageLayout
      id="workspace-panel-map"
      ariaLabel="Project map"
      className="tree-graph-view"
      title="Map"
      description="Explore the product idea, pillars, features, and sub-features as one product hierarchy."
      status={null}
      primaryAction={null}
      actions={null}
      filters={(
        <>
          <WorkspaceFilterField label="Search map" className="workspace-filter-search">
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a pillar, feature, or note" aria-label="Search product map" />
          </WorkspaceFilterField>
          <WorkspaceFilterField label="Layer">
            <select value={layerFilter} onChange={(event) => setLayerFilter(event.target.value)} aria-label="Filter product map by layer">
              {LAYER_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </WorkspaceFilterField>
          <WorkspaceFilterField label="Pillar">
            <select value={pillarFilter} onChange={(event) => setPillarFilter(event.target.value)} aria-label="Filter product map by pillar">
              <option value="all">All pillars</option>
              {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.name}</option>)}
            </select>
          </WorkspaceFilterField>
          <WorkspaceFilterField label="Status">
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filter product map by status">
              <option value="all">All statuses</option>
              {statuses.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
            </select>
          </WorkspaceFilterField>
          <WorkspaceFilterField label="Heatmap">
            <select value={heatmapMode} onChange={(event) => setHeatmapMode(event.target.value)} aria-label="Choose map heatmap metric">
              {HEATMAP_MODES.map((mode) => <option key={mode.id} value={mode.id}>{mode.label}</option>)}
            </select>
          </WorkspaceFilterField>
        </>
      )}
      details={renderDetails()}
    >
      <section className="map-canvas-panel">
        <div className="map-panel-heading">
          <div>
            <h4>Map canvas</h4>
            <p className="muted">Click anywhere on a node for details. Double-click or use Open in layer to navigate.</p>
          </div>
          {heatmapMode !== "none" ? (
            <div className="map-heatmap-legend" aria-label={`${activeHeatmap.label} legend`}>
              <span>Heatmap: <strong>{activeHeatmap.label}</strong></span>
              <span className="tree-legend-item high">High</span>
              <span className="tree-legend-item medium">Medium</span>
              <span className="tree-legend-item low">Low</span>
              <span className="tree-legend-item neutral">No score</span>
            </div>
          ) : null}
        </div>
        {filteredTree ? (
          <div ref={wrapperRef} className="tree-graph-canvas">
            <div className="map-branch-controls" role="group" aria-label="Map branch controls">
              <button type="button" className="secondary-button" onClick={() => remountWithDepth(undefined)}>Expand all</button>
              <button type="button" className="secondary-button" onClick={() => remountWithDepth(0)}>Collapse all</button>
            </div>
            <div className="map-canvas-controls" role="group" aria-label="Map zoom controls">
              <button type="button" className="map-icon-button" onClick={() => changeZoom(-ZOOM_STEP)} aria-label="Zoom out" title="Zoom out">−</button>
              <span className="tree-zoom-readout" aria-live="polite">{Math.round(zoom * 100)}%</span>
              <button type="button" className="map-icon-button" onClick={() => changeZoom(ZOOM_STEP)} aria-label="Zoom in" title="Zoom in">+</button>
              <span className="map-control-divider" aria-hidden="true" />
              <button type="button" className="map-icon-button" onClick={fitToView} aria-label="Fit map to view" title="Fit map to view">⛶</button>
              <button type="button" className="map-icon-button" onClick={resetView} aria-label="Reset map view and filters" title="Reset map view and filters">↺</button>
            </div>
            <Tree
              key={treeKey}
              data={filteredTree}
              orientation="vertical"
              translate={translate}
              zoom={zoom}
              zoomable
              draggable
              scaleExtent={{ min: MIN_ZOOM, max: MAX_ZOOM }}
              initialDepth={initialDepth}
              nodeSize={{ x: 300, y: 182 }}
              separation={{ siblings: 1.25, nonSiblings: 1.55 }}
              pathFunc="step"
              renderCustomNodeElement={renderNode}
            />
          </div>
        ) : (
          <div className="tree-empty-state panel">
            <strong>No nodes match this map view.</strong>
            <p className="muted">The current search, layer, pillar, and status filters hide every branch.</p>
            <button type="button" onClick={clearFilters} disabled={!hasFilters}>Clear filters</button>
          </div>
        )}
      </section>
    </WorkspacePageLayout>
  );
}
