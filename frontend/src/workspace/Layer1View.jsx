import { useMemo, useState } from "react";
import { layer1Pillars } from "./workspaceSelectors";

function searchableText(values) {
  return values.filter(Boolean).join(" ").toLowerCase();
}

export default function Layer1View({
  snapshot,
  onGenerate,
  onCreatePillar,
  onNodeSave,
  onResearch,
  generationJobState,
  researchJobState,
}) {
  const pillars = layer1Pillars(snapshot);
  const [selectedIds, setSelectedIds] = useState([]);
  const [newPillarOpen, setNewPillarOpen] = useState(false);
  const [newPillar, setNewPillar] = useState({ title: "", description: "" });
  const [mergeNotice, setMergeNotice] = useState("");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("priority");
  const generationRunning = generationJobState?.state === "running";
  const researchRunning = researchJobState?.state === "running";
  const allReviewed = pillars.length > 0 && pillars.every((pillar) => pillar.status !== "generated");
  const selectedPillars = useMemo(() => pillars.filter((pillar) => selectedIds.includes(pillar.id)), [pillars, selectedIds]);
  const visiblePillars = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = normalizedQuery
      ? pillars.filter((pillar) => searchableText([pillar.title, pillar.description, pillar.status, pillar.source]).includes(normalizedQuery))
      : pillars;
    return [...filtered].sort((left, right) => {
      if (sortKey === "title") return left.title.localeCompare(right.title);
      if (sortKey === "status") return (left.status || "").localeCompare(right.status || "");
      if (sortKey === "source") return (left.source || "").localeCompare(right.source || "");
      return (left.priority ?? 99) - (right.priority ?? 99) || left.title.localeCompare(right.title);
    });
  }, [pillars, query, sortKey]);

  function toggleSelection(id) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function createPillar(event) {
    event.preventDefault();
    await onCreatePillar?.({ ...newPillar, status: "kept" });
    setNewPillar({ title: "", description: "" });
    setNewPillarOpen(false);
  }

  function mergeFallback() {
    if (selectedPillars.length < 2) return;
    setMergeNotice("Pillar merge is not a backend capability yet. For v1, edit the retained pillar text and mark the others cut.");
  }

  function toggleAllVisible() {
    const visibleIds = visiblePillars.map((pillar) => pillar.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
    setSelectedIds((current) => allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : Array.from(new Set([...current, ...visibleIds])));
  }

  async function applySelected(status) {
    const targets = selectedIds.filter((id) => pillars.some((pillar) => pillar.id === id));
    await Promise.all(targets.map((id) => onNodeSave(id, { status })));
    setSelectedIds((current) => current.filter((id) => !targets.includes(id)));
  }

  return (
    <section className="workspace-layer-panel" id="workspace-panel-layer1" role="tabpanel" aria-label="Layer 1 pillars">
      <div className="workspace-toolbar panel">
        <button type="button" onClick={onGenerate} disabled={generationRunning}>
          {generationRunning ? "Generating..." : generationJobState?.state === "failed" ? "Retry generation" : "Regenerate"}
        </button>
        <button type="button" className="secondary-button" onClick={onResearch} disabled={researchRunning || !pillars.length}>
          {researchRunning ? "Research running..." : researchJobState?.state === "failed" ? "Retry deep research" : "Run deep research"}
        </button>
        <button type="button" className="secondary-button" onClick={() => setNewPillarOpen((open) => !open)}>Add pillar</button>
        <button type="button" className="secondary-button" onClick={mergeFallback} disabled={selectedIds.length < 2}>Merge selected</button>
        <span aria-live="polite">{selectedIds.length ? `${selectedIds.length} selected` : `${visiblePillars.length} of ${pillars.length} pillars`}</span>
      </div>

      <div className="workspace-list-controls panel">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search pillars" aria-label="Search Layer 1 pillars" />
        <select value={sortKey} onChange={(event) => setSortKey(event.target.value)} aria-label="Sort Layer 1 pillars">
          <option value="priority">Sort by priority</option>
          <option value="title">Sort by title</option>
          <option value="status">Sort by status</option>
          <option value="source">Sort by source</option>
        </select>
        <button type="button" className="secondary-button" onClick={toggleAllVisible} disabled={!visiblePillars.length}>Select visible</button>
        <button type="button" className="secondary-button" onClick={() => applySelected("kept")} disabled={!selectedIds.length}>Keep selected</button>
        <button type="button" className="secondary-button" onClick={() => applySelected("cut")} disabled={!selectedIds.length}>Reject selected</button>
      </div>

      {mergeNotice ? <div className="status-banner">{mergeNotice}</div> : null}
      {generationJobState?.state === "failed" ? <div className="warning">Layer 1 generation failed. Check Analytics for job detail, then retry.</div> : null}
      {researchJobState?.state === "failed" ? <div className="warning">Layer 1 research failed. Check Analytics for job detail, then retry.</div> : null}

      {newPillarOpen ? (
        <form className="panel layer-card-form" onSubmit={createPillar}>
          <label>
            Pillar title
            <input value={newPillar.title} onChange={(event) => setNewPillar({ ...newPillar, title: event.target.value })} required />
          </label>
          <label>
            Description
            <textarea value={newPillar.description} onChange={(event) => setNewPillar({ ...newPillar, description: event.target.value })} rows={3} />
          </label>
          <div className="button-row">
            <button type="submit" disabled={!newPillar.title.trim()}>Save pillar</button>
            <button type="button" className="secondary-button" onClick={() => setNewPillarOpen(false)}>Cancel</button>
          </div>
        </form>
      ) : null}

      {visiblePillars.length ? (
        <div className="workspace-table-wrap">
          <table className="workspace-review-table">
            <thead>
              <tr>
                <th scope="col">Select</th>
                <th scope="col">Pillar</th>
                <th scope="col">Status</th>
                <th scope="col">Source</th>
                <th scope="col">Priority</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visiblePillars.map((pillar) => (
                <tr key={pillar.id}>
                  <td><input type="checkbox" checked={selectedIds.includes(pillar.id)} onChange={() => toggleSelection(pillar.id)} aria-label={`Select ${pillar.title}`} /></td>
                  <td>
                    <strong>{pillar.title}</strong>
                    <p className="muted">{pillar.description || "No description yet."}</p>
                  </td>
                  <td><span className={`status-pill ${pillar.status}`}>{pillar.status}</span></td>
                  <td>{pillar.source || "generated"}</td>
                  <td>{pillar.priority ?? "-"}</td>
                  <td>
                    <div className="button-row">
                      <button type="button" className="secondary-button" onClick={() => onNodeSave(pillar.id, { status: "kept" })}>Keep</button>
                      <button type="button" className="secondary-button" onClick={() => onNodeSave(pillar.id, { status: "cut" })}>Reject</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="panel guided-empty-state">
          <strong>{pillars.length ? "No pillars match the current search." : "No pillars yet."}</strong>
          <p className="muted">{pillars.length ? "Clear the search to bring the full list back." : "Publish Layer 0, then generate or add pillars manually."}</p>
        </div>
      )}

      <div className="workspace-footer-action">
        <button type="button" disabled={!allReviewed}>Proceed to Layer 2</button>
      </div>
    </section>
  );
}
