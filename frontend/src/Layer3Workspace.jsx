import { useEffect, useMemo, useState } from "react";
import "./Layer3Workspace.css";

const ARRAY_SECTIONS = [
  ["supported_variants", "Supported variants"],
  ["configurable_options", "Configurable options"],
  ["product_behaviors", "Product behaviors"],
  ["validation_constraints", "Validation and constraint concepts"],
  ["lifecycle_states", "User-facing states and lifecycle"],
  ["dependencies", "Dependencies"],
  ["overlaps_conflicts", "Overlaps and conflicts"],
  ["edge_cases", "Edge cases"],
  ["product_risks", "Product risks"],
];

const RERUN_SECTIONS = [
  ["product_purpose", "Purpose"],
  ["feature_archetype", "Archetype"],
  ...ARRAY_SECTIONS,
  ["relationships", "Relationships"],
  ["open_decisions", "Open decisions"],
];

function cardDraft(card) {
  // Convert a stored card into editable text while keeping structured arrays visible.
  if (!card) return null;
  return {
    product_purpose: card.product_purpose || "",
    feature_archetype: card.feature_archetype || "",
    ...Object.fromEntries(ARRAY_SECTIONS.map(([key]) => [key, JSON.stringify(card[key] || [], null, 2)])),
    relationships: JSON.stringify((card.relationships || []).map(({ id, project_id, card_id, source_feature_id, created_at, ...edge }) => edge), null, 2),
    open_decisions: JSON.stringify((card.open_decisions || []).map(({ id, project_id, card_id, status, resolution, created_at, updated_at, ...decision }) => decision), null, 2),
  };
}

export default function Layer3Workspace({
  layer3,
  thinkingEnabled,
  onThinkingChange,
  onGenerate,
  onSave,
  onReview,
  onPressureTest,
  onDecision,
  onExport,
}) {
  // Keep card generation, review, and downstream readiness in one Layer 3 workspace.
  const eligible = layer3?.eligible_features || [];
  const featureDirectory = layer3?.feature_directory || eligible;
  const cards = layer3?.cards || [];
  const [selectedFeatureIds, setSelectedFeatureIds] = useState([]);
  const [selectedCardId, setSelectedCardId] = useState("");
  const [draft, setDraft] = useState(null);
  const [editorError, setEditorError] = useState("");
  const [rerunSections, setRerunSections] = useState([]);
  const [resolutionDrafts, setResolutionDrafts] = useState({});
  const selectedCard = useMemo(
    () => cards.find((card) => card.id === selectedCardId) || cards[0] || null,
    [cards, selectedCardId],
  );
  const persistedDraft = useMemo(() => cardDraft(selectedCard), [selectedCard]);
  const hasUnsavedEdits = Boolean(
    draft && persistedDraft && JSON.stringify(draft) !== JSON.stringify(persistedDraft),
  );

  useEffect(() => {
    if (selectedCard && selectedCard.id !== selectedCardId) setSelectedCardId(selectedCard.id);
    setDraft(cardDraft(selectedCard));
    setEditorError("");
  }, [selectedCard?.id, selectedCard?.updated_at]);

  async function saveCard() {
    // Parse edited JSON sections only when the user explicitly saves the card.
    setEditorError("");
    try {
      const payload = {
        product_purpose: draft.product_purpose,
        feature_archetype: draft.feature_archetype,
      };
      ARRAY_SECTIONS.forEach(([key]) => {
        payload[key] = JSON.parse(draft[key] || "[]");
      });
      payload.relationships = JSON.parse(draft.relationships || "[]");
      payload.open_decisions = JSON.parse(draft.open_decisions || "[]");
      await onSave(selectedCard.id, payload);
    } catch (error) {
      const message = error instanceof SyntaxError
        ? "One of the structured section editors contains invalid JSON."
        : error.message;
      setEditorError(message);
    }
  }

  function toggleFeature(featureId, checked) {
    setSelectedFeatureIds((current) => checked ? [...current, featureId] : current.filter((id) => id !== featureId));
  }

  function toggleRerun(section, checked) {
    setRerunSections((current) => checked ? [...current, section] : current.filter((item) => item !== section));
  }

  function selectCard(cardId) {
    // Do not silently discard a partially edited card when switching the review target.
    if (hasUnsavedEdits) {
      setEditorError("Save or discard the current edits before switching cards.");
      return;
    }
    setSelectedCardId(cardId);
  }

  function discardEdits() {
    // Restore the latest persisted card after an abandoned edit.
    setDraft(persistedDraft);
    setEditorError("");
  }

  async function runWorkspaceAction(action) {
    // Keep rejected API actions visible in the Layer 3 workspace without unhandled promises.
    setEditorError("");
    try {
      await action();
    } catch (error) {
      setEditorError(error.message);
    }
  }

  return (
    <div className="layer3-workspace">
      <section className="panel layer3-generation-panel">
        <div className="layer3-heading">
          <div>
            <span className="eyebrow">Capability Design Layer</span>
            <h3>Turn approved features into reviewable product definitions</h3>
            <p className="muted">Layer 3 clarifies behavior, options, states, relationships, risks, and decisions without producing implementation specs.</p>
          </div>
          <button type="button" className="secondary-button" onClick={() => runWorkspaceAction(onExport)} disabled={hasUnsavedEdits || !cards.some((card) => card.review_state === "approved")}>
            Export approved cards
          </button>
        </div>
        <div className="layer3-eligible-grid">
          {eligible.length ? eligible.map((feature) => {
            const hasCard = cards.some((card) => card.feature_id === feature.id);
            return (
              <label key={feature.id} className="layer3-feature-choice">
                <input type="checkbox" checked={selectedFeatureIds.includes(feature.id)} onChange={(event) => toggleFeature(feature.id, event.target.checked)} />
                <span>
                  <strong>{feature.canonical_name}</strong>
                  <small>{hasCard ? "Card exists - regenerate all sections" : "Ready for first card"}</small>
                </span>
              </label>
            );
          }) : <p className="muted">Approve Layer 2 features to make them eligible for Capability Design.</p>}
        </div>
        <div className="button-row">
          <label className="inline-check"><input type="checkbox" checked={thinkingEnabled} onChange={(event) => onThinkingChange(event.target.checked)} /> Thinking</label>
          <button type="button" onClick={() => runWorkspaceAction(() => onGenerate(selectedFeatureIds, []))} disabled={hasUnsavedEdits || !selectedFeatureIds.length}>Generate cards</button>
        </div>
      </section>
      {editorError ? <p className="error-banner" role="alert">{editorError}</p> : null}

      {cards.length ? (
        <div className="layer3-review-layout">
          <aside className="panel layer3-card-list">
            <h3>Capability cards</h3>
            {cards.map((card) => (
              <button key={card.id} type="button" className={card.id === selectedCard?.id ? "layer3-card-link active" : "layer3-card-link"} onClick={() => selectCard(card.id)}>
                <strong>{card.feature_name}</strong>
                <span>{card.feature_archetype}</span>
                <small>{card.review_state} - readiness {card.downstream_readiness_score}</small>
              </button>
            ))}
          </aside>

          {selectedCard && draft ? (
            <section className="layer3-card-editor">
              <div className="panel">
                <div className="layer3-heading">
                  <div>
                    <span className="eyebrow">{selectedCard.parent_pillar_title}</span>
                    <h3>{selectedCard.feature_name}</h3>
                    <p className="muted">{selectedCard.feature_description}</p>
                  </div>
                  <div className={`readiness-score readiness-${selectedCard.downstream_readiness_score >= 80 ? "high" : selectedCard.downstream_readiness_score >= 60 ? "medium" : "low"}`}>
                    <strong>{selectedCard.downstream_readiness_score}</strong>
                    <span>downstream readiness</span>
                  </div>
                </div>
                <label>Product purpose<textarea rows={4} value={draft.product_purpose} onChange={(event) => setDraft({ ...draft, product_purpose: event.target.value })} /></label>
                <label>Feature archetype<input value={draft.feature_archetype} onChange={(event) => setDraft({ ...draft, feature_archetype: event.target.value })} /></label>
                {ARRAY_SECTIONS.map(([key, label]) => (
                  <details key={key} className="layer3-section" open={["product_behaviors", "edge_cases"].includes(key)}>
                    <summary>{label}</summary>
                    <textarea aria-label={label} rows={8} value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
                  </details>
                ))}
                <div className="button-row">
                  <button type="button" onClick={saveCard}>Save edits</button>
                  {hasUnsavedEdits ? <button type="button" className="ghost-button" onClick={discardEdits}>Discard edits</button> : null}
                  <button type="button" className="secondary-button" disabled={hasUnsavedEdits} onClick={() => runWorkspaceAction(() => onPressureTest(selectedCard.id))}>Rerun pressure test</button>
                  <button type="button" className="secondary-button" disabled={hasUnsavedEdits || selectedCard.pressure_test?.stale} onClick={() => runWorkspaceAction(() => onReview(selectedCard.id, "approve"))}>Approve</button>
                  <button type="button" className="secondary-button" disabled={hasUnsavedEdits} onClick={() => runWorkspaceAction(() => onReview(selectedCard.id, "needs_review"))}>Needs review</button>
                  <button type="button" className="danger-button" disabled={hasUnsavedEdits} onClick={() => runWorkspaceAction(() => onReview(selectedCard.id, "reject"))}>Reject</button>
                </div>
              </div>

              <section className="panel">
                <h3>Relationships</h3>
                <textarea aria-label="Relationship definitions" rows={7} value={draft.relationships} onChange={(event) => setDraft({ ...draft, relationships: event.target.value })} />
                <div className="layer3-edge-list">
                  {(selectedCard.relationships || []).map((edge) => {
                    const target = featureDirectory.find((feature) => feature.id === edge.target_feature_id);
                    return <div key={edge.id}><strong>{edge.relationship_type}</strong><span>{target?.canonical_name || edge.target_feature_id}</span><p>{edge.rationale}</p></div>;
                  })}
                  {!selectedCard.relationships?.length ? <p className="muted">No product relationship edges detected.</p> : null}
                </div>
              </section>

              <section className="panel">
                <h3>Open decisions</h3>
                <textarea aria-label="Open decision definitions" rows={7} value={draft.open_decisions} onChange={(event) => setDraft({ ...draft, open_decisions: event.target.value })} />
                {(selectedCard.open_decisions || []).map((decision) => (
                  <div key={decision.id} className="layer3-decision">
                    <div><strong>{decision.question}</strong><span className={`status-pill ${decision.status}`}>{decision.status}</span></div>
                    {decision.context ? <p>{decision.context}</p> : null}
                    {decision.options?.length ? <ul>{decision.options.map((option) => <li key={option}>{option}</li>)}</ul> : null}
                    <textarea rows={2} placeholder="Resolution" value={resolutionDrafts[decision.id] ?? decision.resolution ?? ""} onChange={(event) => setResolutionDrafts({ ...resolutionDrafts, [decision.id]: event.target.value })} />
                    <div className="button-row">
                      <button type="button" className="secondary-button" onClick={() => runWorkspaceAction(() => onDecision(decision.id, "resolved", resolutionDrafts[decision.id] ?? decision.resolution ?? ""))}>Mark resolved</button>
                      <button type="button" className="ghost-button" onClick={() => runWorkspaceAction(() => onDecision(decision.id, "unresolved", ""))}>Reopen</button>
                    </div>
                  </div>
                ))}
                {!selectedCard.open_decisions?.length ? <p className="muted">No unresolved product decisions.</p> : null}
              </section>

              <section className="panel">
                <h3>Pressure test</h3>
                <p>{selectedCard.readiness_rationale}</p>
                {Object.entries(selectedCard.pressure_test || {}).filter(([key, value]) => Array.isArray(value) && value.length).map(([key, value]) => (
                  <div key={key} className="pressure-group"><strong>{key.replaceAll("_", " ")}</strong><ul>{value.map((item) => <li key={item}>{item}</li>)}</ul></div>
                ))}
              </section>

              <section className="panel">
                <h3>Rerun selected sections</h3>
                <div className="checkbox-grid">
                  {RERUN_SECTIONS.map(([key, label]) => (
                    <label key={key} className="checkbox-item"><input type="checkbox" checked={rerunSections.includes(key)} onChange={(event) => toggleRerun(key, event.target.checked)} /><span>{label}</span></label>
                  ))}
                </div>
                <button type="button" onClick={() => runWorkspaceAction(() => onGenerate([selectedCard.feature_id], rerunSections))} disabled={hasUnsavedEdits || !rerunSections.length}>Regenerate selected sections</button>
              </section>
            </section>
          ) : null}
        </div>
      ) : <section className="panel"><h3>No Capability Design Cards yet</h3><p className="muted">Select approved Layer 2 features above to begin Layer 3.</p></section>}
    </div>
  );
}
