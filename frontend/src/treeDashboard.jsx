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
  truncate,
  withDerivedFields,
} from "./treeDashboardData";

// Shows compact counts for total, visible, overlap, and per-layer nodes.
import { DashboardStats, GraphToolbar, LayerRail, NodeDetail, TreeCanvas } from "./treeDashboardComponents";
export { NodeDetail };
export default function TreeDashboard({
  project,
  brief,
  tree,
  findings,
  layer2Graph,
  selectedId: selectedIdProp,
  mapState,
  onSelectionChange,
  onMapStateChange,
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
  generationControls,
}) {
  // Interactive product map with filtering, collapse state, and overlap overlays.
  const root = useMemo(() => withDerivedFields(buildRootNode(project, brief, tree)), [project, brief, tree]);
  const fullIndex = useMemo(() => buildTreeIndex(root), [root]);
  const overlapData = useMemo(() => {
    const base = collectOverlapEdges(root);
    const relationshipEdges = (layer2Graph?.relationships || []).map((relationship) => ({
      id: relationship.id,
      from: relationship.source_feature_id,
      to: relationship.target_feature_id,
      type: relationship.relationship_type,
      detail: relationship.reason || relationship.relationship_type,
      score: Number(relationship.confidence || 0),
    }));
    return { ...base, edges: [...base.edges, ...relationshipEdges] };
  }, [root, layer2Graph?.relationships]);
  const [collapsedIds, setCollapsedIds] = useState(() => new Set(mapState?.collapsed_ids || createInitialCollapsedSet(root)));
  const [query, setQuery] = useState(mapState?.filters?.query || "");
  const [layerFilter, setLayerFilter] = useState(mapState?.filters?.layer || "all");
  const [statusFilter, setStatusFilter] = useState(mapState?.filters?.status || "all");
  const [overlapMode, setOverlapMode] = useState(mapState?.overlap_mode || "focus");
  const [zoom, setZoom] = useState(mapState?.zoom || 1);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const selectedId = selectedIdProp || root.id;

  function selectNode(nodeId) {
    const entity = fullIndex.byId[nodeId];
    if (entity) {
      setCollapsedIds((current) => {
        const next = new Set(current);
        next.delete(nodeId);
        return next;
      });
      onSelectionChange?.(entity);
      setInspectorOpen(true);
    }
  }

  useEffect(() => {
    setCollapsedIds(new Set(mapState?.collapsed_ids || createInitialCollapsedSet(root)));
    setQuery(mapState?.filters?.query || "");
    setLayerFilter(mapState?.filters?.layer || "all");
    setStatusFilter(mapState?.filters?.status || "all");
    setOverlapMode(mapState?.overlap_mode || "focus");
    setZoom(mapState?.zoom || 1);
    setInspectorOpen(false);
  }, [root.id, project?.id]);

  useEffect(() => {
    onMapStateChange?.({
      zoom,
      overlap_mode: overlapMode,
      collapsed_ids: Array.from(collapsedIds),
      filters: { query, layer: layerFilter, status: statusFilter },
    });
  }, [zoom, overlapMode, collapsedIds, query, layerFilter, statusFilter]);

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
    selectNode(nextId);
  }, [selectedId, visibleIds, filteredRoot.id, filteredIndex.order, query]);

  useEffect(() => {
    if (!query.trim()) {
      return;
    }
    const nextMatch = filteredIndex.order.find((id) => id !== root.id);
    if (!nextMatch) {
      return;
    }
    selectNode(nextMatch);
    setCollapsedIds((current) => {
      const next = new Set(current);
      (fullIndex.ancestorsById[nextMatch] || []).forEach((ancestorId) => next.delete(ancestorId));
      return next;
    });
  }, [query, filteredIndex.order, fullIndex.ancestorsById, root.id]);

  const selectedNode = fullIndex.byId[selectedId] || fullIndex.byId[filteredRoot.id] || null;
  const parentNode = selectedNode ? fullIndex.byId[selectedNode.parent_id] || null : null;
  const childNodes = selectedNode ? (selectedNode.children || []) : [];
  const siblingNodes = parentNode ? (parentNode.children || []).filter((item) => item.id !== selectedNode?.id) : [];
  const breadcrumbs = selectedNode ? [...(fullIndex.ancestorsById[selectedNode.id] || []), selectedNode.id].map((id) => fullIndex.byId[id]).filter(Boolean) : [];
  const focusedRoot = selectedNode?.layer > 0
    ? filterTree(selectedNode, { query, layerFilter, statusFilter }) || selectedNode
    : filteredRoot;
  const focusedGraph = useMemo(() => buildVisibleGraph(focusedRoot, collapsedIds), [focusedRoot, collapsedIds]);

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

  useEffect(() => {
    function handleEscape(event) {
      if (event.key !== "Escape" || !parentNode) return;
      if (event.target?.closest?.("input, textarea, select, [role='dialog'], .assistant-drawer")) return;
      selectNode(parentNode.id);
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [parentNode?.id]);

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

      <details className="panel tree-view-options">
        <summary>
          <span>View options</span>
          <span className="muted">{stats.visibleNodes} visible | {stats.overlapEdges} overlaps</span>
        </summary>
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
      </details>

      <div className="tree-focus-navigation panel">
        <div className="tree-breadcrumbs">
          {breadcrumbs.map((item) => <button key={item.id} type="button" className="link-button" onClick={() => selectNode(item.id)}>{item.title}</button>)}
        </div>
        {siblingNodes.length ? (
          <div className="tree-sibling-rail">
            <span className="muted">Parallel branches</span>
            {siblingNodes.map((item) => <button key={item.id} type="button" className="tree-chip" onClick={() => selectNode(item.id)}>{item.title}</button>)}
          </div>
        ) : null}
        <button type="button" className="secondary-button tree-inspector-toggle" onClick={() => setInspectorOpen((current) => !current)}>
          {inspectorOpen ? "Hide Inspector" : "Inspect Selection"}
        </button>
      </div>

      <div className={inspectorOpen ? "tree-workspace" : "tree-workspace inspector-closed"}>
        <LayerRail
          counts={stats.perLayer}
          visibleCounts={stats.visiblePerLayer}
          layerFilter={layerFilter}
          onLayerFilterChange={setLayerFilter}
        />

        <div className="panel tree-visual-panel">
          <TreeCanvas
            graph={focusedGraph}
            selectedId={selectedNode?.id}
            onSelect={selectNode}
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

        {inspectorOpen ? <div className="panel tree-detail-panel">
          <NodeDetail
            node={selectedNode}
            brief={brief}
            findings={findings}
            parentNode={parentNode}
            childNodes={childNodes}
            overlapLinks={overlapLinks}
            onSelectNode={selectNode}
            onSaveNode={onSaveNode}
            pillars={fullIndex.order.map((id) => fullIndex.byId[id]).filter((item) => item.entity_type === "pillar")}
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
        </div> : null}
      </div>
    </section>
  );
}
