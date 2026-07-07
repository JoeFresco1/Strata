import { useMemo, useState } from "react";
import ColumnHeader from "./ColumnHeader";
import { layer1Pillars } from "./workspaceSelectors";
import WorkspacePageLayout, { WorkspaceActionButton, WorkspaceActionGroup, WorkspaceStatusBadge } from "./WorkspacePage";
import WorkspaceJobNotice from "./WorkspaceJobNotice";

function searchableText(values) {
  return values.filter(Boolean).join(" ").toLowerCase();
}

function relationLabel(value) {
  return String(value || "").replaceAll("_", " ");
}

function compareValues(left, right, direction) {
  const leftMissing = left === null || left === undefined || left === "";
  const rightMissing = right === null || right === undefined || right === "";
  if (leftMissing && rightMissing) return 0;
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  const result = typeof left === "number" && typeof right === "number"
    ? left - right
    : String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" });
  return direction === "asc" ? result : -result;
}

export default function Layer1View({
  snapshot,
  onGenerate,
  onCreatePillar,
  onNodeSave,
  onOverlapCritic,
  onResolveOverlap,
  onResearch,
  generationJobState,
  researchJobState,
  overlapJobState,
  onCancelJob,
  competitiveIntelligenceEnabled = true,
}) {
  const pillars = layer1Pillars(snapshot);
  const [selectedIds, setSelectedIds] = useState([]);
  const [newPillarOpen, setNewPillarOpen] = useState(false);
  const [newPillar, setNewPillar] = useState({ title: "", description: "" });
  const [mergeNotice, setMergeNotice] = useState("");
  const [query, setQuery] = useState("");
  const [sortConfig, setSortConfig] = useState({ key: "priority", direction: "asc" });
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewFilter, setReviewFilter] = useState("unresolved");
  const generationRunning = generationJobState?.state === "running";
  const researchRunning = researchJobState?.state === "running";
  const overlapRunning = overlapJobState?.state === "running";
  const overlapVerdicts = snapshot?.overlap?.layer1?.verdicts || [];
  const pillarById = useMemo(() => Object.fromEntries(pillars.map((pillar) => [pillar.id, pillar])), [pillars]);
  const reviewVerdicts = useMemo(() => (
    overlapVerdicts.filter((verdict) => {
      if (verdict.relation === "distinct") return false;
      if (reviewFilter === "all") return true;
      return (verdict.resolution_state || "unresolved") === reviewFilter;
    })
  ), [overlapVerdicts, reviewFilter]);
  const overlapByTarget = useMemo(() => {
    const grouped = new Map();
    overlapVerdicts.forEach((verdict) => {
      if (["distinct"].includes(verdict.relation)) return;
      grouped.set(verdict.target_id, [...(grouped.get(verdict.target_id) || []), verdict]);
      grouped.set(verdict.neighbor_id, [...(grouped.get(verdict.neighbor_id) || []), verdict]);
    });
    return grouped;
  }, [overlapVerdicts]);
  const allReviewed = pillars.length > 0 && pillars.every((pillar) => pillar.status !== "generated");
  const selectedPillars = useMemo(() => pillars.filter((pillar) => selectedIds.includes(pillar.id)), [pillars, selectedIds]);
  const visiblePillars = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = normalizedQuery
      ? pillars.filter((pillar) => searchableText([pillar.title, pillar.description, pillar.status, pillar.source]).includes(normalizedQuery))
      : pillars;
    return [...filtered].sort((left, right) => {
      const selectors = {
        title: (pillar) => pillar.title,
        status: (pillar) => pillar.status,
        source: (pillar) => pillar.source || "generated",
        priority: (pillar) => pillar.priority,
      };
      const select = selectors[sortConfig.key] || selectors.priority;
      return compareValues(select(left), select(right), sortConfig.direction) || left.title.localeCompare(right.title);
    });
  }, [pillars, query, sortConfig]);

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
    setMergeNotice("Pillar merge is not a backend capability yet. For v1, edit the retained pillar text and mark the others rejected.");
  }

  function toggleAllVisible() {
    const visibleIds = visiblePillars.map((pillar) => pillar.id);
    const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));
    setSelectedIds((current) => allVisibleSelected ? current.filter((id) => !visibleIds.includes(id)) : Array.from(new Set([...current, ...visibleIds])));
  }

  function toggleSort(key) {
    setSortConfig((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  }

  async function applySelected(status) {
    const targets = selectedIds.filter((id) => pillars.some((pillar) => pillar.id === id));
    await Promise.all(targets.map((id) => onNodeSave(id, { status })));
    setSelectedIds((current) => current.filter((id) => !targets.includes(id)));
  }

  async function resolveVerdict(verdict, action) {
    await onResolveOverlap?.(verdict.id, { action });
    if (action === "accept_merge") mergeFallback();
  }

  function activeResearchForPillar(pillarId) {
    return (researchJobState?.jobs || []).find((job) => (
      job.scope_id === pillarId && ["queued", "running"].includes(job.status)
    ));
  }

  return (
    <WorkspacePageLayout
      id="workspace-panel-layer1"
      ariaLabel="Layer 1 pillars"
      title="Pillars"
      description="Review, research, and curate the major product areas that organize downstream feature work."
      status={!pillars.length ? "draft" : allReviewed ? "approved" : "needs_review"}
      primaryAction={(
        <WorkspaceActionButton
          primary
          onClick={onGenerate}
          disabled={generationRunning}
          disabledReason={generationRunning ? "Layer 1 generation is already running." : ""}
        >
          Generate all
        </WorkspaceActionButton>
      )}
      actions={(
        <>
          <WorkspaceActionGroup label="Generate">
            <WorkspaceActionButton secondary onClick={() => setNewPillarOpen((open) => !open)}>Add pillar</WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Research">
            <WorkspaceActionButton
              secondary
              onClick={onResearch}
              disabled={researchRunning || !pillars.length}
              disabledReason={researchRunning ? "Layer 1 research is already running." : !pillars.length ? "Generate or add pillars before research." : ""}
            >
              Research all
            </WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Review / Critique">
            <WorkspaceActionButton
              secondary
              onClick={onOverlapCritic}
              disabled={overlapRunning || pillars.length < 2}
              disabledReason={overlapRunning ? "Overlap critique is already running." : pillars.length < 2 ? "At least two pillars are required." : ""}
            >
              Run overlap critic
            </WorkspaceActionButton>
            <WorkspaceActionButton
              secondary
              onClick={() => setReviewOpen((open) => !open)}
              disabled={!overlapVerdicts.length}
              disabledReason={!overlapVerdicts.length ? "Run the overlap critic before reviewing verdicts." : ""}
            >
              Review selected ({overlapVerdicts.filter((verdict) => verdict.relation !== "distinct" && (verdict.resolution_state || "unresolved") !== "resolved").length})
            </WorkspaceActionButton>
          </WorkspaceActionGroup>
          <WorkspaceActionGroup label="Selection actions">
            <WorkspaceActionButton secondary onClick={toggleAllVisible} disabled={!visiblePillars.length} disabledReason={!visiblePillars.length ? "No visible pillars to select." : ""}>Select all</WorkspaceActionButton>
            <WorkspaceActionButton secondary onClick={() => applySelected("kept")} disabled={!selectedIds.length} disabledReason={!selectedIds.length ? "Select pillars first." : ""}>Keep selected</WorkspaceActionButton>
            <WorkspaceActionButton secondary destructive={Boolean(selectedIds.length)} onClick={() => applySelected("cut")} disabled={!selectedIds.length} disabledReason={!selectedIds.length ? "Select pillars first." : ""}>Reject selected</WorkspaceActionButton>
            <WorkspaceActionButton secondary onClick={mergeFallback} disabled={selectedIds.length < 2} disabledReason={selectedIds.length < 2 ? "Select at least two pillars to merge." : ""}>Merge selected</WorkspaceActionButton>
            <span className="workspace-selection-count" aria-live="polite">{selectedIds.length ? `${selectedIds.length} selected` : `${visiblePillars.length} of ${pillars.length} pillars`}</span>
          </WorkspaceActionGroup>
        </>
      )}
      filters={(
        <>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search pillars" aria-label="Search Layer 1 pillars" />
        <label>
          Sort by
          <select value={sortConfig.key} onChange={(event) => setSortConfig({ ...sortConfig, key: event.target.value })} aria-label="Sort pillars">
            <option value="priority">Priority</option>
            <option value="title">Pillar</option>
            <option value="status">Status</option>
            <option value="source">Source</option>
          </select>
        </label>
        <WorkspaceActionButton secondary onClick={() => setSortConfig((current) => ({ ...current, direction: current.direction === "asc" ? "desc" : "asc" }))}>
          {sortConfig.direction === "asc" ? "Ascending" : "Descending"}
        </WorkspaceActionButton>
        </>
      )}
    >

      {mergeNotice ? <div className="status-banner">{mergeNotice}</div> : null}
      <WorkspaceJobNotice jobState={generationJobState} label="Layer 1 generation" onCancel={onCancelJob} />
      <WorkspaceJobNotice jobState={researchJobState} label="Layer 1 research" onCancel={onCancelJob} />
      <WorkspaceJobNotice jobState={overlapJobState} label="Layer 1 overlap critic" onCancel={onCancelJob} />
      {generationJobState?.state === "failed" ? <div className="warning">Layer 1 generation failed. Check Analytics for job detail, then retry.</div> : null}
      {researchJobState?.state === "failed" ? <div className="warning">Layer 1 research failed. Check Analytics for job detail, then retry.</div> : null}
      {overlapJobState?.state === "failed" ? <div className="warning">Layer 1 overlap critic failed. Check Analytics for job detail, then retry.</div> : null}

      {reviewOpen ? (
        <section className="panel overlap-review-panel" aria-label="Layer 1 overlap review">
          <div className="workspace-section-heading">
            <div>
              <strong>Overlap review</strong>
              <p className="muted">Resolve explainable critic verdicts. Layer 1 merge records the decision; edit/mark pillars manually for now.</p>
            </div>
            <select value={reviewFilter} onChange={(event) => setReviewFilter(event.target.value)} aria-label="Filter overlap verdicts">
              <option value="unresolved">Unresolved</option>
              <option value="resolved">Resolved</option>
              <option value="stale_resolution">Stale resolutions</option>
              <option value="all">All</option>
            </select>
          </div>
          {reviewVerdicts.length ? (
            <div className="overlap-review-list">
              {reviewVerdicts.map((verdict) => {
                const target = pillarById[verdict.target_id];
                const neighbor = pillarById[verdict.neighbor_id];
                const resolved = verdict.resolution_state === "resolved";
                return (
                  <article className="overlap-review-item" key={verdict.id}>
                    <div>
                      <strong>{target?.title || verdict.target_id}</strong>
                      <span className="muted"> overlaps with </span>
                      <strong>{neighbor?.title || verdict.neighbor_id}</strong>
                      <p className="muted">{relationLabel(verdict.relation)} · confidence {Math.round(Number(verdict.confidence || 0) * 100)}%</p>
                      <p>{verdict.rationale || "No rationale returned."}</p>
                      {verdict.active_resolution ? <p className="muted">Resolved as {relationLabel(verdict.active_resolution.action)}.</p> : null}
                      {verdict.resolution_state === "stale_resolution" ? <p className="warning">Prior decision is stale because one item changed. Rerun or resolve again.</p> : null}
                    </div>
                    <div className="button-row">
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "accept_merge")} disabled={resolved}>Accept merge</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "link")} disabled={resolved}>Link</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "keep_separate")} disabled={resolved}>Keep separate</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "dismiss")} disabled={resolved}>Dismiss</button>
                      <button type="button" className="secondary-button" onClick={() => resolveVerdict(verdict, "needs_followup")} disabled={resolved}>Needs follow-up</button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="muted">No overlap verdicts match this filter.</p>
          )}
        </section>
      ) : null}

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
            <button type="submit" className="secondary-button" disabled={!newPillar.title.trim()}>Save pillar</button>
            <button type="button" className="secondary-button" onClick={() => setNewPillarOpen(false)}>Cancel</button>
          </div>
        </form>
      ) : null}

      {visiblePillars.length ? (
        <div className="workspace-table-wrap">
          <table className="workspace-review-table">
            <thead>
              <tr>
                <th scope="col"><ColumnHeader label="Select" description="Choose one or more pillars for bulk keep, reject, or future batch actions." /></th>
                <th scope="col"><ColumnHeader label="Pillar" description="The Layer 1 product capability and its working description." sortKey="title" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Status" description="Current review decision for this pillar, such as generated, kept, or rejected." sortKey="status" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Source" description="Where the pillar came from, usually model generation or a manual entry." sortKey="source" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Priority" description="Relative ordering signal used to sort and review the most important pillars first." sortKey="priority" activeSortKey={sortConfig.key} sortDirection={sortConfig.direction} onSort={toggleSort} /></th>
                <th scope="col"><ColumnHeader label="Actions" description="Row-level controls to research, keep, reject, or otherwise manage this pillar." /></th>
              </tr>
            </thead>
            <tbody>
              {visiblePillars.map((pillar) => (
                <tr key={pillar.id}>
                  <td><input type="checkbox" checked={selectedIds.includes(pillar.id)} onChange={() => toggleSelection(pillar.id)} aria-label={`Select ${pillar.title}`} /></td>
                  <td>
                    <strong>
                      {pillar.title}
                      {overlapByTarget.get(pillar.id)?.length ? <span className="warning-icon" title="Flagged by overlap critic" aria-label={`Overlap critic warning for ${pillar.title}`}>!</span> : null}
                    </strong>
                    <p className="muted">{pillar.description || "No description yet."}</p>
                    {overlapByTarget.get(pillar.id)?.length ? (
                      <p className="muted critic-source-line">Overlap critic: {overlapByTarget.get(pillar.id)[0].relation.replaceAll("_", " ")} - {overlapByTarget.get(pillar.id)[0].rationale}</p>
                    ) : null}
                  </td>
                  <td><WorkspaceStatusBadge status={pillar.status} /></td>
                  <td>{pillar.source || "generated"}</td>
                  <td>{pillar.priority ?? "-"}</td>
                  <td>
                    <div className="button-row">
                      {(() => {
                        const activeResearch = activeResearchForPillar(pillar.id);
                        return (
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => onResearch?.([pillar.id])}
                            disabled={!competitiveIntelligenceEnabled || Boolean(activeResearch)}
                            title={competitiveIntelligenceEnabled ? `Research row: ${pillar.title}` : "Competitive intelligence is off in project settings."}
                          >
                            {activeResearch ? "Researching..." : "Research row"}
                          </button>
                        );
                      })()}
                      <button type="button" className="secondary-button" onClick={() => onNodeSave(pillar.id, { status: "kept" })}>Keep</button>
                      <button type="button" className="secondary-button danger-button" onClick={() => onNodeSave(pillar.id, { status: "cut" })}>Reject</button>
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
        <button type="button" className="secondary-button" disabled={!allReviewed}>Proceed to Layer 2</button>
      </div>
    </WorkspacePageLayout>
  );
}
