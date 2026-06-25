export const NODE_WIDTH = 280;
export const NODE_HEIGHT = 132;
export const HORIZONTAL_GAP = 156;
export const VERTICAL_GAP = 54;
export const CANVAS_PADDING = 56;
export const CANVAS_TOP_PADDING = 92;
export const MIN_ZOOM = 0.7;
export const MAX_ZOOM = 1.7;
export const STATUS_OPTIONS = ["generated", "kept", "cut", "merged", "prioritized", "draft", "published"];
export const OVERLAP_MODE_OPTIONS = [
  { value: "focus", label: "Focus" },
  { value: "heatmap", label: "Heatmap" },
  { value: "overlap", label: "Overlap View" },
];

// Constrains zoom and pan values to the supported canvas range.
export function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

// Shortens long labels while preserving readable card text.
export function truncate(value, maxLength) {
  if (!value) {
    return "";
  }
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 3)}...`;
}

// Converts a numeric layer into the UI label used across the dashboard.
export function formatLayerLabel(layer) {
  return `Layer ${layer}`;
}

// Normalizes backend node type keys for display.
export function formatNodeType(value) {
  return (value || "node").replaceAll("_", " ");
}

// Creates the synthetic Layer 0 root node that anchors the generated tree.
export function buildRootNode(project, brief, tree) {
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

// Adds parent and child-count defaults to backend tree nodes.
export function withDerivedFields(node, parentId = null) {
  const children = (node.children || []).map((child) => withDerivedFields(child, node.id));
  return {
    ...node,
    parent_id: node.parent_id ?? parentId,
    child_count: node.child_count ?? children.length,
    children,
  };
}

// Builds fast lookup maps used by selection, filtering, and canvas rendering.
export function buildTreeIndex(root) {
  const byId = {};
  const parentById = {};
  const ancestorsById = {};
  const collapsibleIds = [];
  const byLayer = new Map();
  const order = [];

  // Walks the tree once while recording ancestry and layer counts.
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

// Starts deeper layers collapsed so the first render stays scannable.
export function createInitialCollapsedSet(root) {
  const collapsed = new Set();

  // Records nodes that can be expanded by the user.
  function visit(node) {
    if (node.layer >= 1 && node.children?.length) {
      collapsed.add(node.id);
    }
    (node.children || []).forEach(visit);
  }

  visit(root);
  return collapsed;
}

// Collects duplicate, semantic, and stale-research edges for graph overlays.
export function collectOverlapEdges(root) {
  const index = buildTreeIndex(root);
  const edges = [];
  const degree = {};
  const researchByNode = {};
  const seen = new Set();

  // Adds a deduped overlay edge only when both endpoints exist in the tree.
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
    const overlapRelationships = node.json_payload?.overlap_relationships || [];
    overlapRelationships.forEach((relationship) => {
      addEdge(
        node.id,
        relationship.target_node_id,
        relationship.relationship_type || "cluster_neighbor",
        relationship.detail || `Cluster overlap ${relationship.score}`,
        Number(relationship.score || 0),
      );
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

// Tests one node against the active search/layer/status controls.
export function matchesFilters(node, filters) {
  const query = filters.query.trim().toLowerCase();
  const searchableText = [node.title, node.description, node.node_type, node.status].filter(Boolean).join(" ").toLowerCase();
  const queryMatch = !query || searchableText.includes(query);
  const layerMatch = filters.layerFilter === "all" || String(node.layer) === filters.layerFilter;
  const statusMatch = filters.statusFilter === "all" || node.status === filters.statusFilter;
  return queryMatch && layerMatch && statusMatch;
}

// Prunes the tree while keeping ancestors needed to reach matching children.
export function filterTree(node, filters) {
  const children = (node.children || [])
    .map((child) => filterTree(child, filters))
    .filter(Boolean);
  const includeSelf = node.layer === 0 || matchesFilters(node, filters);
  if (!includeSelf && !children.length) {
    return null;
  }
  return { ...node, child_count: node.child_count ?? children.length, children };
}

// Collects ids remaining after filters so overlay edges can be hidden correctly.
export function collectVisibleIds(root) {
  const ids = new Set();
  // Depth-first walk over the already-filtered tree.
  function visit(node) {
    ids.add(node.id);
    (node.children || []).forEach(visit);
  }
  visit(root);
  return ids;
}

// Lays out the visible tree into deterministic canvas coordinates.
export function buildVisibleGraph(root, collapsedIds) {
  const nodes = [];
  const edges = [];
  const byId = {};
  let maxDepth = 0;
  let nextLeafY = CANVAS_TOP_PADDING;

  // Recursively places children before centering the parent above them.
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
    baseLayer: Number(root.layer || 0),
    maxDepth,
    width: CANVAS_PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * HORIZONTAL_GAP,
    height: Math.max(520, nextLeafY + CANVAS_PADDING),
  };
}

// Chooses the visual tone class for a node card.
export function nodeTone(node) {
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
  if (node.node_type === "feature") {
    return "subfeature";
  }
  if (node.node_type === "subfeature") {
    return "subfeature";
  }
  return "pillar";
}

// Builds the compact metadata table for the selected node drawer.
export function detailRowsForNode(node, parentNode) {
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

