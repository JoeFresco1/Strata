import { useState } from "react";
import { approvedLayer2Features, getLayer3Expansions } from "./workspaceSelectors";

function optionCount(expansion) {
  return (expansion.expansion_groups || []).reduce((total, group) => total + (group.options || []).length, 0);
}

function includedCount(expansion) {
  return (expansion.expansion_groups || []).reduce(
    (total, group) => total + (group.options || []).filter((option) => option.selection_state === "include").length,
    0,
  );
}

export default function Layer3View({
  snapshot,
  onGenerate,
  onReviewExpansion,
  generationJobState,
}) {
  const expansions = getLayer3Expansions(snapshot);
  const approvedFeatures = approvedLayer2Features(snapshot);
  const [expandedIds, setExpandedIds] = useState(new Set());
  const generationRunning = generationJobState?.state === "running";

  function toggleExpanded(id) {
    setExpandedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function expansionDetail(expansion) {
    return (
      <div className="layer3-expansion-detail">
        <p className="muted">{expansion.feature_intent || expansion.feature_description || "No feature intent recorded."}</p>
        {(expansion.expansion_groups || []).map((group) => (
          <div key={group.id || group.name} className="layer3-option-group">
            <strong>{group.name}</strong>
            {group.description ? <p className="muted">{group.description}</p> : null}
            <div className="layer3-option-list">
              {(group.options || []).map((option) => (
                <span key={option.id || option.name} className={`status-pill ${option.selection_state}`}>
                  {option.name}: {option.selection_state}
                </span>
              ))}
            </div>
          </div>
        ))}
        {expansion.open_questions?.length ? (
          <ul className="summary-list">
            {expansion.open_questions.map((question) => <li key={question}>{question}</li>)}
          </ul>
        ) : null}
        <div className="button-row">
          <button type="button" onClick={() => onReviewExpansion(expansion.id, "approve")}>Approve</button>
          <button type="button" className="secondary-button" onClick={() => onReviewExpansion(expansion.id, "needs_review")}>Needs review</button>
          <button type="button" className="secondary-button" onClick={() => onReviewExpansion(expansion.id, "reject")}>Reject</button>
        </div>
      </div>
    );
  }

  return (
    <section className="workspace-layer-panel" id="workspace-panel-layer3" role="tabpanel" aria-label="Layer 3 details">
      <div className="workspace-toolbar panel">
        <button type="button" onClick={() => onGenerate(approvedFeatures.map((feature) => feature.id))} disabled={generationRunning || !approvedFeatures.length}>
          {generationRunning ? "Generating..." : generationJobState?.state === "failed" ? "Retry Layer 3 generation" : "Generate details"}
        </button>
        <span>{approvedFeatures.length} approved feature{approvedFeatures.length === 1 ? "" : "s"} ready for expansion</span>
      </div>
      {generationJobState?.state === "failed" ? <div className="warning">Layer 3 generation failed. Check Analytics for details.</div> : null}

      {!expansions.length ? (
        <div className="panel guided-empty-state">
          <strong>No Layer 3 expansions yet.</strong>
          <p className="muted">Approve Layer 2 features, then generate details.</p>
        </div>
      ) : (
        <div className="workspace-table-wrap">
          <table className="workspace-review-table">
            <thead>
              <tr>
                <th scope="col">Feature</th>
                <th scope="col">Pillar</th>
                <th scope="col">Sub-items</th>
                <th scope="col">Status</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {expansions.map((expansion) => (
                <tr key={expansion.id}>
                  <td>
                    <strong>{expansion.feature_name}</strong>
                    {expandedIds.has(expansion.id) ? expansionDetail(expansion) : null}
                  </td>
                  <td>{expansion.parent_pillar_title}</td>
                  <td>{includedCount(expansion)} / {optionCount(expansion)}</td>
                  <td><span className={`status-pill ${expansion.review_state}`}>{expansion.review_state}</span></td>
                  <td>
                    <button type="button" className="secondary-button" onClick={() => toggleExpanded(expansion.id)} aria-expanded={expandedIds.has(expansion.id)}>
                      {expandedIds.has(expansion.id) ? "Collapse" : "Expand"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
