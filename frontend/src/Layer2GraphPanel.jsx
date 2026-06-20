import "./Layer2GraphPanel.css";

// Presents the graph-native Layer 2 review queue as a pillar-grouped hierarchy.
function Layer2GraphPanel({ graph, pillars, onReview }) {
  const features = graph?.features || [];
  const relationships = graph?.relationships || [];
  const affinity = graph?.affinity || [];
  const reviewActions = graph?.review_actions || [];
  const negativeCache = graph?.negative_cache || [];
  const coverage = graph?.coverage || [];
  const pillarById = Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar]));
  const featuresByOwner = features.reduce((groups, feature) => {
    const key = feature.owner_pillar_id || "unassigned";
    groups[key] = groups[key] || [];
    groups[key].push(feature);
    return groups;
  }, {});

  if (!features.length) {
    return (
      <div className="panel">
        <h3>Layer 2 Feature Graph</h3>
        <p className="muted">Generate Layer 2 from kept pillars to populate the review queue.</p>
      </div>
    );
  }

  return (
    <div className="panel layer2-graph-panel">
      <div className="panel-header">
        <h3>Layer 2 Feature Graph</h3>
        <span>{features.filter((feature) => ["candidate", "needs_review"].includes(feature.status)).length} open reviews</span>
      </div>
      <div className="info-grid">
        <div>
          <strong>Features</strong>
          <p>{features.length}</p>
        </div>
        <div>
          <strong>Relationships</strong>
          <p>{relationships.length}</p>
        </div>
        <div>
          <strong>Coverage Reviews</strong>
          <p>{coverage.length}</p>
        </div>
      </div>
      {coverage.length ? (
        <div className="layer2-coverage-strip">
          {coverage.map((item) => {
            const openFamilies = (item.content?.family_assessments || []).filter((family) =>
              ["missing", "partial"].includes(family.status),
            );
            return (
              <div key={item.id} className="layer2-coverage-card">
                <strong>{item.content?.scope_contract?.pillar_name || "Layer 2 Scope"}</strong>
                <p>{item.content?.coverage_summary || "No summary."}</p>
                <p>
                  {item.content?.saturation_signal || "unknown"} saturation | novelty {item.content?.novelty_score ?? 0}/100
                </p>
                {openFamilies.length ? (
                  <p className="warning">Open families: {openFamilies.map((family) => `${family.family} (${family.status})`).join(", ")}</p>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}
      <div className="info-grid">
        <div>
          <strong>Negative Cache</strong>
          <p>{negativeCache.length}</p>
        </div>
        <div>
          <strong>Review Actions</strong>
          <p>{reviewActions.length}</p>
        </div>
      </div>
      {Object.entries(featuresByOwner).map(([pillarId, ownerFeatures]) => (
        <div key={pillarId} className="layer2-owner-group">
          <h4>{pillarById[pillarId]?.title || "Unassigned"}</h4>
          <div className="layer2-feature-grid">
            {ownerFeatures.map((feature) => {
              const duplicateEdges = relationships.filter(
                (edge) => edge.source_feature_id === feature.id || edge.target_feature_id === feature.id,
              );
              const featureAffinity = affinity.filter((item) => item.feature_id === feature.id);
              return (
                <div key={feature.id} className={`layer2-feature-card ${feature.status}`}>
                  <div className="panel-header">
                    <strong>{feature.canonical_name}</strong>
                    <span className="status-pill">{feature.status}</span>
                  </div>
                  <p>{feature.description}</p>
                  <div className="meta-block">
                    <p>
                      {feature.feature_type} | fit {feature.pillar_fit_score}/100 | distinct {feature.distinctiveness_score}/100 | leakage{" "}
                      {feature.implementation_leakage_score}/100
                    </p>
                    {feature.metadata?.coverage_family ? <p>Family: {feature.metadata.coverage_family}</p> : null}
                    {feature.metadata?.scope_classification ? <p>Scope: {feature.metadata.scope_classification}</p> : null}
                    {feature.metadata?.pillar_fit_rationale ? <p>{feature.metadata.pillar_fit_rationale}</p> : null}
                    {feature.metadata?.scope_drift_flag ? <p className="warning">Scope drift flagged for review.</p> : null}
                    {feature.aliases?.length ? <p>Aliases: {feature.aliases.join(", ")}</p> : null}
                    {feature.metadata?.negative_cache_match ? <p className="warning">Negative cache: {feature.metadata.negative_cache_reason}</p> : null}
                  </div>
                  {duplicateEdges.length ? (
                    <ul className="summary-list">
                      {duplicateEdges.map((edge) => (
                        <li key={edge.id}>
                          {edge.relationship_type} | strength {edge.strength} | {edge.rationale}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {featureAffinity.length ? (
                    <p className="muted">
                      Owner recommendation: {pillarById[featureAffinity[0].recommended_owner_pillar_id]?.title || featureAffinity[0].recommended_owner_pillar_id}
                    </p>
                  ) : null}
                  <div className="button-row">
                    <button type="button" onClick={() => onReview({ action_type: "keep", feature_id: feature.id })}>
                      Keep
                    </button>
                    <button type="button" onClick={() => onReview({ action_type: "cut", feature_id: feature.id })}>
                      Cut
                    </button>
                    <button type="button" onClick={() => onReview({ action_type: "approve_for_layer3", feature_id: feature.id })}>
                      Approve
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}


export default Layer2GraphPanel;
