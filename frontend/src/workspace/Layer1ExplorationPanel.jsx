import { useCallback, useEffect, useMemo, useState } from "react";
import { WorkspaceActionButton, WorkspaceStatusBadge } from "./WorkspacePage";

function label(value) {
  return String(value || "").replaceAll("_", " ");
}

function pct(value) {
  const numeric = Number(value || 0);
  return `${Math.round(numeric <= 1 ? numeric * 100 : numeric)}%`;
}

function latestPolicies(items) {
  const latest = new Map();
  items.forEach((item) => {
    const current = latest.get(item.logical_id);
    if (!current || Number(item.revision_number) > Number(current.revision_number)) {
      latest.set(item.logical_id, item);
    }
  });
  return [...latest.values()];
}

export default function Layer1ExplorationPanel({ projectId, apiFetch }) {
  const [runs, setRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [candidateFilter, setCandidateFilter] = useState("all");
  const [closedTitle, setClosedTitle] = useState("");
  const [genericTitle, setGenericTitle] = useState("");

  const loadRuns = useCallback(async () => {
    if (!projectId || !apiFetch) return;
    const payload = await apiFetch(`/projects/${projectId}/layer1/exploration-runs`, { force: true });
    const nextRuns = payload.runs || [];
    setRuns(nextRuns);
    setSelectedRunId((current) => current || nextRuns[0]?.id || "");
  }, [apiFetch, projectId]);

  const loadDetail = useCallback(async (runId) => {
    if (!runId || !apiFetch) {
      setDetail(null);
      return;
    }
    const payload = await apiFetch(`/projects/${projectId}/layer1/exploration-runs/${runId}`, { force: true });
    setDetail(payload);
  }, [apiFetch, projectId]);

  useEffect(() => {
    loadRuns().catch((requestError) => setError(requestError.message));
  }, [loadRuns]);

  useEffect(() => {
    loadDetail(selectedRunId).catch((requestError) => setError(requestError.message));
  }, [loadDetail, selectedRunId]);

  const dispositionByCandidate = useMemo(() => Object.fromEntries(
    (detail?.candidate_dispositions || []).map((item) => [item.candidate_id, item]),
  ), [detail]);
  const normalizedByCandidate = useMemo(() => Object.fromEntries(
    (detail?.normalized_territories || []).map((item) => [item.candidate_id, item]),
  ), [detail]);
  const closedTerritories = useMemo(
    () => latestPolicies(detail?.closed_territories || []),
    [detail],
  );
  const genericPatterns = useMemo(
    () => latestPolicies(detail?.anti_generic_patterns || []),
    [detail],
  );
  const visibleCandidates = useMemo(() => {
    const items = detail?.raw_candidates || [];
    if (candidateFilter === "all") return items;
    if (candidateFilter === "weak") return items.filter((item) => item.weakly_attributable);
    return items.filter((item) => dispositionByCandidate[item.id]?.destination === candidateFilter);
  }, [candidateFilter, detail, dispositionByCandidate]);
  const candidateMetrics = detail?.run?.metrics?.candidate_integrity || detail?.global_coverage?.candidate_integrity || {};

  async function perform(key, request, refreshRun = selectedRunId) {
    setBusy(key);
    setError("");
    try {
      const payload = await request();
      await loadRuns();
      await loadDetail(refreshRun || payload?.run?.id);
      if (payload?.run?.id) setSelectedRunId(payload.run.id);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  function startExploration() {
    return perform("start", () => apiFetch(`/projects/${projectId}/layer1/exploration-runs`, {
      method: "POST",
      body: JSON.stringify({
        config: {
          target_raw_candidates: 18,
          minimum_raw_candidates: 12,
          maximum_raw_candidates: 30,
        },
      }),
    }), "");
  }

  function lensAction(lens, action, extras = {}) {
    return perform(`lens:${lens.id}`, () => apiFetch(
      `/projects/${projectId}/layer1/exploration-runs/${selectedRunId}/lenses/${lens.id}`,
      {
        method: "POST",
        body: JSON.stringify({ action, ...extras }),
      },
    ));
  }

  function reclassify(candidateId, destination) {
    return perform(`candidate:${candidateId}`, () => apiFetch(
      `/projects/${projectId}/layer1/territories/${candidateId}/classification`,
      {
        method: "POST",
        body: JSON.stringify({
          destination,
          reason: "Human review in Layer 1 exploration workspace.",
        }),
      },
    ));
  }

  function addClosedTerritory(event) {
    event.preventDefault();
    if (!closedTitle.trim()) return;
    perform("closed:add", () => apiFetch(`/projects/${projectId}/layer1/closed-territories`, {
      method: "POST",
      body: JSON.stringify({
        run_id: selectedRunId,
        title: closedTitle.trim(),
        scope: "run",
        reason: "Added during Layer 1 territory review.",
      }),
    })).then(() => setClosedTitle(""));
  }

  function addGenericPattern(event) {
    event.preventDefault();
    if (!genericTitle.trim()) return;
    perform("generic:add", () => apiFetch(`/projects/${projectId}/layer1/anti-generic-patterns`, {
      method: "POST",
      body: JSON.stringify({
        title: genericTitle.trim(),
        source_run_ids: [selectedRunId],
        confidence: 0.8,
      }),
    })).then(() => setGenericTitle(""));
  }

  if (!apiFetch) {
    return <div className="panel warning">Exploration APIs are unavailable in this workspace.</div>;
  }

  return (
    <div className="layer1-exploration">
      <section className="panel layer1-exploration-hero">
        <div>
          <strong>Territory exploration</strong>
          <p className="muted">Explore each Product Discovery lens independently, preserve every candidate, then compare pillar architectures.</p>
        </div>
        <div className="button-row">
          <WorkspaceActionButton primary onClick={startExploration} disabled={Boolean(busy)}>
            Start exploration
          </WorkspaceActionButton>
          <WorkspaceActionButton secondary onClick={() => loadDetail(selectedRunId)} disabled={!selectedRunId || Boolean(busy)}>
            Refresh
          </WorkspaceActionButton>
        </div>
      </section>

      {error ? <div className="warning" role="alert">{error}</div> : null}

      {runs.length ? (
        <label className="layer1-run-picker">
          Exploration run
          <select value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)}>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {new Date(run.created_at).toLocaleString()} - {label(run.status)}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="panel guided-empty-state">
          <strong>No territory explorations yet.</strong>
          <p className="muted">Publish Product Discovery, then start a run. Existing manually curated pillars remain untouched.</p>
        </div>
      )}

      {detail ? (
        <>
          <section className="layer1-metric-grid" aria-label="Exploration summary">
            <article><span>Run status</span><WorkspaceStatusBadge status={detail.run.status} /></article>
            <article><span>Raw candidates</span><strong>{candidateMetrics.raw_candidates || detail.raw_candidates.length}</strong></article>
            <article><span>Classified</span><strong>{candidateMetrics.classified_candidates || detail.candidate_dispositions.length}</strong></article>
            <article><span>Unresolved</span><strong>{candidateMetrics.undispositioned_candidates || 0}</strong></article>
            <article><span>Lens adherence</span><strong>{pct(detail.global_coverage?.lens_adherence?.average_lens_adherence_score)}</strong></article>
            <article><span>Generic repetition</span><strong>{pct(detail.global_coverage?.lens_adherence?.average_generic_repetition_rate)}</strong></article>
          </section>

          {detail.global_coverage?.incomplete_reasons?.length ? (
            <div className="status-banner">
              <strong>Exploration is incomplete.</strong>
              <ul>{detail.global_coverage.incomplete_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
            </div>
          ) : null}

          <section className="panel">
            <div className="workspace-section-heading">
              <div>
                <strong>Lens queue</strong>
                <p className="muted">Required, risk, relevance, coverage, and human priority determine order.</p>
              </div>
            </div>
            <div className="layer1-lens-list">
              {detail.lenses.map((lens) => (
                <article key={lens.id} className="layer1-lens-row">
                  <div>
                    <strong>{lens.title}</strong>
                    <p className="muted">{lens.required ? "Required" : "Optional"} - {lens.attempt_count}/{lens.max_attempts} attempts</p>
                  </div>
                  <WorkspaceStatusBadge status={lens.state} />
                  <div className="button-row compact">
                    <button type="button" className="secondary-button" disabled={busy === `lens:${lens.id}`} onClick={() => lensAction(lens, "run")}>Run</button>
                    <button type="button" className="secondary-button" disabled={busy === `lens:${lens.id}`} onClick={() => lensAction(lens, "retry_stronger_exclusions")}>Stronger exclusions</button>
                    <button type="button" className="secondary-button" disabled={busy === `lens:${lens.id}`} onClick={() => lensAction(lens, "complete", { terminal_state: "intentionally_excluded" })}>Exclude lens</button>
                    <button type="button" className="secondary-button" disabled={busy === `lens:${lens.id}`} onClick={() => lensAction(lens, "reopen")}>Reopen</button>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="workspace-section-heading">
              <div>
                <strong>Candidate reservoir</strong>
                <p className="muted">Raw candidates remain immutable. Classification changes are append-only.</p>
              </div>
              <select value={candidateFilter} onChange={(event) => setCandidateFilter(event.target.value)} aria-label="Filter territory candidates">
                <option value="all">All candidates</option>
                <option value="weak">Weak attribution</option>
                <option value="standalone_pillar_candidate">Pillar candidates</option>
                <option value="layer_2_feature_family">Layer 2 families</option>
                <option value="deferred_human_review">Needs human review</option>
                <option value="duplicate">Duplicates</option>
                <option value="rejected_generic_repetition">Generic repetition</option>
              </select>
            </div>
            <div className="layer1-candidate-list">
              {visibleCandidates.map((candidate) => {
                const disposition = dispositionByCandidate[candidate.id];
                const normalized = normalizedByCandidate[candidate.id];
                return (
                  <article key={candidate.id} className="layer1-candidate-card">
                    <div>
                      <strong>{candidate.title}</strong>
                      {candidate.weakly_attributable ? <span className="warning">Weak attribution</span> : null}
                      <p>{candidate.description || "No description returned."}</p>
                      {normalized && normalized.normalized_title !== candidate.title ? <p className="muted">Normalized as: {normalized.normalized_title}</p> : null}
                      <p className="muted">{candidate.lens_specific_mechanism || "No lens-specific mechanism supplied."}</p>
                    </div>
                    <label>
                      Destination
                      <select
                        value={disposition?.destination || "deferred_human_review"}
                        disabled={busy === `candidate:${candidate.id}`}
                        onChange={(event) => reclassify(candidate.id, event.target.value)}
                      >
                        <option value="standalone_pillar_candidate">Standalone pillar candidate</option>
                        <option value="cross_cutting_product_concern">Cross-cutting concern</option>
                        <option value="enterprise_platform_obligation">Enterprise obligation</option>
                        <option value="pillar_extension">Pillar extension</option>
                        <option value="layer_2_feature_family">Layer 2 feature family</option>
                        <option value="actor_workspace">Actor workspace</option>
                        <option value="operational_capability">Operational capability</option>
                        <option value="commercial_capability">Commercial capability</option>
                        <option value="developer_platform_capability">Developer platform capability</option>
                        <option value="workflow_family">Workflow family</option>
                        <option value="decision_mechanism">Decision mechanism</option>
                        <option value="data_responsibility">Data responsibility</option>
                        <option value="governance_mechanism">Governance mechanism</option>
                        <option value="strategic_opportunity">Strategic opportunity</option>
                        <option value="deferred_human_review">Deferred human review</option>
                        <option value="duplicate">Duplicate</option>
                        <option value="out_of_scope">Out of scope</option>
                        <option value="rejected_quality">Reject: quality</option>
                        <option value="rejected_generic_repetition">Reject: generic repetition</option>
                        <option value="rejected_unsupported">Reject: unsupported</option>
                        <option value="rejected_bizarre">Reject: bizarre</option>
                      </select>
                    </label>
                    <details>
                      <summary>Lineage and provenance</summary>
                      <p className="muted">Lens {candidate.source_lens_id}</p>
                      <p className="muted">Discovery items: {candidate.source_discovery_item_ids.join(", ") || "none"}</p>
                      <p className="muted">Model: {candidate.runtime_provenance?.exact_model_identifier || candidate.runtime_provenance?.model_alias || "unknown"}</p>
                      <p className="muted">Temperature: {candidate.runtime_provenance?.effective_temperature}</p>
                    </details>
                  </article>
                );
              })}
            </div>
            {detail.semantic_clusters?.length ? (
              <div className="layer1-cluster-strip" aria-label="Semantic clusters">
                {detail.semantic_clusters.map((cluster) => (
                  <span key={cluster.id}>{cluster.title} ({cluster.candidate_ids.length})</span>
                ))}
              </div>
            ) : null}
          </section>

          <section className="panel layer1-policy-panel">
            <div className="workspace-section-heading">
              <div>
                <strong>Exclusions and anti-generic patterns</strong>
                <p className="muted">Only active human-approved revisions affect later independent prompts.</p>
              </div>
            </div>
            <div className="layer1-policy-columns">
              <div>
                <strong>Closed territory</strong>
                <form className="layer1-policy-form" onSubmit={addClosedTerritory}>
                  <input value={closedTitle} onChange={(event) => setClosedTitle(event.target.value)} placeholder="Semantic family already covered" />
                  <button type="submit" className="secondary-button" disabled={!closedTitle.trim() || Boolean(busy)}>Add</button>
                </form>
                <ul>
                  {closedTerritories.map((item) => (
                    <li key={item.logical_id}>
                      <span>{item.title} - {item.active ? "active" : "reopened"}</span>
                      {item.active ? <button type="button" className="text-button" onClick={() => perform(`closed:${item.logical_id}`, () => apiFetch(`/projects/${projectId}/layer1/closed-territories/${item.logical_id}`, { method: "DELETE" }))}>Reopen</button> : null}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <strong>Anti-generic patterns</strong>
                <form className="layer1-policy-form" onSubmit={addGenericPattern}>
                  <input value={genericTitle} onChange={(event) => setGenericTitle(event.target.value)} placeholder="Repeated generic product shape" />
                  <button type="submit" className="secondary-button" disabled={!genericTitle.trim() || Boolean(busy)}>Add</button>
                </form>
                <ul>
                  {genericPatterns.map((item) => (
                    <li key={item.logical_id}>
                      <span>{item.title} - {item.active ? "active" : "disabled"}</span>
                      {item.active ? <button type="button" className="text-button" onClick={() => perform(`generic:${item.logical_id}`, () => apiFetch(`/projects/${projectId}/layer1/anti-generic-patterns/${item.logical_id}`, { method: "DELETE" }))}>Disable</button> : null}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="workspace-section-heading">
              <div>
                <strong>Blind spots and synthesis</strong>
                <p className="muted">Adversarial scenarios run separately. Architectures are generated only when exploration is ready.</p>
              </div>
              <div className="button-row">
                <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => perform("adversarial", () => apiFetch(`/projects/${projectId}/layer1/exploration-runs/${selectedRunId}/adversarial`, { method: "POST", body: JSON.stringify({ role: "skeptical implementation consultant" }) }))}>Run blind-spot pass</button>
                <button type="button" className="secondary-button" disabled={Boolean(busy) || !detail.global_coverage?.ready_for_synthesis} onClick={() => perform("synthesis", () => apiFetch(`/projects/${projectId}/layer1/exploration-runs/${selectedRunId}/synthesis`, { method: "POST" }))}>Generate architectures</button>
              </div>
            </div>
            {detail.adversarial_findings.length ? (
              <ul>{detail.adversarial_findings.map((item) => <li key={item.id}><strong>{item.missing_product_territory}</strong> - {item.concrete_failure}</li>)}</ul>
            ) : <p className="muted">No adversarial findings yet.</p>}
            <div className="layer1-architecture-grid">
              {detail.architecture_options.map((architecture) => (
                <article key={architecture.id} className="layer1-architecture-card">
                  <WorkspaceStatusBadge status={architecture.kind} />
                  <strong>{architecture.title}</strong>
                  <p>{architecture.rationale}</p>
                  <p className="muted">{architecture.pillars.length} pillars - {architecture.significant_non_pillar_territory_ids.length} retained non-pillar territories</p>
                  <button type="button" className="secondary-button" onClick={() => perform(`select:${architecture.id}`, () => apiFetch(`/projects/${projectId}/layer1/exploration-runs/${selectedRunId}/selection`, { method: "POST", body: JSON.stringify({ architecture_candidate_id: architecture.id }) }))}>Select this option</button>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
