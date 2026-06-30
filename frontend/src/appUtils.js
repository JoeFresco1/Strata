export const TABS = [
  { id: "Workspace", label: "Workspace" },
  { id: "Layer 0", label: "Brief" },
  { id: "Specs", label: "Capability Design" },
  { id: "Analytics", label: "Analytics" },
  { id: "Project", label: "Project Settings" },
];

export function sortProjects(projects, sortOrder) {
  // Keep project library ordering deterministic after refreshes.
  return [...projects].sort((left, right) => {
    if (sortOrder === "name") {
      return String(left.name || "").localeCompare(String(right.name || ""), undefined, { sensitivity: "base" });
    }
    const field = sortOrder === "last_opened" ? "last_opened_at" : sortOrder === "newest" || sortOrder === "oldest" ? "created_at" : "updated_at";
    const leftTime = left[field] ? new Date(left[field]).getTime() : 0;
    const rightTime = right[field] ? new Date(right[field]).getTime() : 0;
    return sortOrder === "oldest" ? leftTime - rightTime : rightTime - leftTime;
  });
}

export function approvedNodes(nodes, nodeType) {
  // Keep only the items a human approved for downward expansion.
  return nodes.filter((node) => node.node_type === nodeType && ["kept", "prioritized"].includes(node.status));
}

export function findWorkspaceEntity(workspaceTree, selectedId) {
  // Traverse the small workspace tree once to recover the durable selection.
  const stack = [...workspaceTree];
  while (stack.length) {
    const item = stack.shift();
    if (item.id === selectedId) return item;
    stack.push(...(item.children || []));
  }
  return workspaceTree[0] || null;
}

export function assistantScopeFor(activeTab, selectedEntity) {
  // Map the visible workspace selection to the assistant retrieval scope.
  if (activeTab === "Specs") return "layer3";
  if ([0, 1, 2].includes(selectedEntity?.layer)) return `layer${selectedEntity.layer}`;
  return "overall";
}

export function applyAssistantNavigation({ layer, citation = {}, setActiveTab, setWorkspaceState }) {
  // Translate assistant citations into the matching workspace tab and durable entity selection.
  if (layer === "layer3") {
    setActiveTab("Specs");
    return;
  }
  setActiveTab("Workspace");
  const targetId = layer === "layer0"
    ? "layer0-root"
    : citation.entity_id || citation.scope_id || citation.source_entity_id || citation.source_id
      || citation.metadata?.feature_id || citation.metadata?.pillar_id;
  if (!targetId) return;
  setWorkspaceState((current) => ({
    ...(current || {}),
    selected_entity_id: targetId,
    selected_entity_type: layer === "layer2" ? "feature" : layer === "layer1" ? "pillar" : "brief",
  }));
}
