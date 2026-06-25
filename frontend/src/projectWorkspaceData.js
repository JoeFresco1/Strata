// Build the canonical Layer 0-2 workspace projection from brief, pillar, and graph state.
export function buildWorkspaceTree(project, brief, nodes, layer2Graph) {
  const features = layer2Graph?.workbench?.rows || layer2Graph?.features || [];
  const featuresByPillar = {};
  features.forEach((feature) => {
    const ownerId = feature.owner_pillar_id || "unassigned";
    featuresByPillar[ownerId] = [...(featuresByPillar[ownerId] || []), feature];
  });

  const pillars = nodes
    .filter((node) => node.layer === 1 && node.node_type === "pillar")
    .sort((left, right) => (left.priority ?? 99) - (right.priority ?? 99) || left.title.localeCompare(right.title))
    .map((pillar) => ({
      ...pillar,
      entity_type: "pillar",
      children: (featuresByPillar[pillar.id] || [])
        .sort((left, right) => left.canonical_name.localeCompare(right.canonical_name))
        .map((feature) => ({
          id: feature.id,
          parent_id: pillar.id,
          title: feature.canonical_name,
          description: feature.description || "",
          layer: 2,
          node_type: "feature",
          entity_type: "feature",
          status: feature.status,
          priority: feature.priority || null,
          json_payload: feature,
          child_count: 0,
          children: [],
        })),
    }));

  return [{
    id: "layer0-root",
    parent_id: null,
    title: project?.name || "Untitled Project",
    description: brief?.product_idea || project?.idea || "",
    layer: 0,
    node_type: "brief",
    entity_type: "brief",
    status: brief?.status || "draft",
    priority: null,
    json_payload: { brief },
    child_count: pillars.length,
    children: pillars,
  }];
}

// Return a flat entity list for Table mode while retaining hierarchy metadata.
export function flattenWorkspaceTree(root) {
  const rows = [];
  function visit(node, ancestors = []) {
    rows.push({ ...node, ancestors, depth: ancestors.length });
    (node.children || []).forEach((child) => visit(child, [...ancestors, node.id]));
  }
  if (root) visit(root);
  return rows;
}

// Convert Layer 2 graph relationships into overlays understood by the map.
export function workspaceRelationshipEdges(layer2Graph) {
  return (layer2Graph?.relationships || []).map((relationship) => ({
    id: relationship.id,
    from: relationship.source_feature_id,
    to: relationship.target_feature_id,
    type: relationship.relationship_type,
    detail: relationship.reason || relationship.relationship_type,
    score: Number(relationship.confidence || 0),
  }));
}
