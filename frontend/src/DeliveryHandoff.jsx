import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "./apiClient";

export default function DeliveryHandoff({ projectId, cards = [] }) {
  const [preview, setPreview] = useState(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const readyIds = useMemo(
    () => new Set((preview?.cards || []).filter((card) => card.ready).map((card) => card.card_id)),
    [preview],
  );
  const cardsSignature = useMemo(
    () => cards.map((card) => `${card.id}:${card.review_state}:${card.updated_at}`).join("|"),
    [cards],
  );

  useEffect(() => {
    if (!projectId) return undefined;
    let active = true;
    async function loadPreview() {
      try {
        const payload = await apiFetch(`/projects/${projectId}/delivery/speckit`, { force: true, silent: true });
        if (!active) return;
        setPreview(payload);
        setSelectedIds(payload.cards.filter((card) => card.ready).map((card) => card.card_id));
      } catch (previewError) {
        if (active) setError(previewError.message);
      }
    }
    loadPreview();
    return () => {
      active = false;
    };
  }, [projectId, cardsSignature]);

  function toggleCard(cardId, checked) {
    setSelectedIds((current) => checked ? [...current, cardId] : current.filter((id) => id !== cardId));
  }

  async function createHandoff() {
    setError("");
    setResult(null);
    setLoading(true);
    try {
      const payload = await apiFetch(`/projects/${projectId}/delivery/speckit`, {
        method: "POST",
        body: JSON.stringify({ card_ids: selectedIds }),
      });
      setResult(payload);
    } catch (handoffError) {
      setError(handoffError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel delivery-handoff">
      <div className="layer3-heading">
        <div>
          <span className="eyebrow">Delivery handoff</span>
          <h3>Move approved Layer 3 cards into Spec Kit</h3>
          <p className="muted">Exports Spec Kit-ready `spec.md` seeds with Strata lineage and traceability. Planning and tasks still happen inside the target repo.</p>
        </div>
        <button type="button" onClick={createHandoff} disabled={loading || !selectedIds.length}>
          {loading ? "Creating..." : "Create Spec Kit bundle"}
        </button>
      </div>
      {error ? <p className="error-banner" role="alert">{error}</p> : null}
      {preview ? (
        <div className="delivery-card-grid">
          {preview.cards.map((card) => (
            <label key={card.card_id} className={card.ready ? "delivery-card ready" : "delivery-card blocked"}>
              <input
                type="checkbox"
                checked={selectedIds.includes(card.card_id)}
                disabled={!readyIds.has(card.card_id)}
                onChange={(event) => toggleCard(card.card_id, event.target.checked)}
              />
              <span>
                <strong>{card.feature_name}</strong>
                <small>{card.ready ? `Ready - score ${card.readiness_score}` : card.blockers.join(" ")}</small>
              </span>
            </label>
          ))}
          {!preview.cards.length ? <p className="muted">Approve Capability Design Cards before creating a delivery handoff.</p> : null}
        </div>
      ) : <p className="muted">Checking delivery readiness...</p>}
      {result ? (
        <div className="export-result" role="status">
          <strong>Spec Kit handoff created</strong>
          <span>Folder: {result.output_dir}</span>
          <span>ZIP: {result.zip_path}</span>
          <span>{result.slice_count} implementation slice{result.slice_count === 1 ? "" : "s"} exported.</span>
        </div>
      ) : null}
    </section>
  );
}
