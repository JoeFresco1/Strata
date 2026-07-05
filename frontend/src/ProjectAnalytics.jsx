import { useEffect, useState } from "react";
import "./ProjectAnalytics.css";

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

function formatCost(value) {
  return `$${Number(value || 0).toFixed(4)}`;
}

function Metric({ label, value, detail }) {
  return (
    <div className="analytics-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function Breakdown({ title, rows }) {
  return (
    <div className="panel analytics-breakdown">
      <h3>{title}</h3>
      {rows?.length ? (
        <div className="analytics-table">
          {rows.map((row) => (
            <div className="analytics-row" key={row.name}>
              <strong>{row.name}</strong>
              <span data-label="Tokens">{formatNumber(row.total_tokens)} tokens</span>
              <span data-label="Calls">{formatNumber(row.calls)} calls</span>
              <span data-label="Cost">{formatCost(row.estimated_cost_usd)}</span>
              <span data-label="Time">{Number(row.generation_seconds || 0).toFixed(1)}s</span>
            </div>
          ))}
        </div>
      ) : <p className="muted">No model calls have been captured yet.</p>}
    </div>
  );
}

function failureCategory(job) {
  const text = `${job.error_type || ""} ${job.error_message || ""}`.toLowerCase();
  if (!text.trim()) return "";
  if (/(model|llm|openai|completion|token|context|endpoint|timeout|connection|http|api key)/.test(text)) return "Model provider";
  if (/(database|postgres|sqlite|pgvector|psycopg|sql|migration)/.test(text)) return "Database";
  if (/(crawl|crawler|scrape|fetch|requests|ssl|url|domain|trafilatura|beautifulsoup)/.test(text)) return "Crawler";
  if (/(json|parse|parser|schema|validation|pydantic|malformed)/.test(text)) return "Parser";
  return "Application";
}

function JobQueue({ jobs, onCancel, onRetry, busy }) {
  const rows = jobs || [];
  return (
    <div className="panel">
      <h3>Unified job queue</h3>
      {rows.length ? (
        <div className="job-table">
          {rows.map((job) => (
            <div className="job-row" key={job.id}>
              {failureCategory(job) ? <span className="status-pill failed" data-label="Failure category">{failureCategory(job)}</span> : null}
              <span className={`status-pill ${job.status}`} data-label="Status">{job.status}</span>
              <strong>{job.workflow}</strong>
              <span data-label="Kind">{job.kind}</span>
              <span data-label="Step">{job.current_step || "Queued"}</span>
              <span data-label="Progress">{formatNumber(job.progress)}%</span>
              {job.error_message ? <span className="warning" data-label="Error">{job.error_message}</span> : <span data-label="Scope">{job.scope}</span>}
              <div className="button-row compact">
                <button type="button" className="secondary-button" onClick={() => onCancel(job.id)} disabled={busy || !["queued", "running"].includes(job.status)}>Cancel</button>
                <button type="button" onClick={() => onRetry(job.id)} disabled={busy || !["failed", "cancelled", "interrupted"].includes(job.status)}>Retry</button>
              </div>
            </div>
          ))}
        </div>
      ) : <p className="muted">Generation, research, assistant, replay, audits, and diagnostics jobs will appear here.</p>}
    </div>
  );
}

export default function ProjectAnalytics({ projectId, apiFetch }) {
  const [analytics, setAnalytics] = useState(null);
  const [health, setHealth] = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [diagnosticsPreview, setDiagnosticsPreview] = useState(null);
  const [diagnosticsOptions, setDiagnosticsOptions] = useState({
    include_logs: true,
    include_recent_errors: true,
    include_traces: true,
    log_line_limit: 400,
    redaction_profile: "standard",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function refresh() {
    const [analyticsPayload, healthPayload] = await Promise.all([
      apiFetch(`/projects/${projectId}/analytics`, { force: true }),
      apiFetch(`/projects/${projectId}/admin-health`, { force: true }),
    ]);
    setAnalytics(analyticsPayload);
    setHealth(healthPayload);
  }

  useEffect(() => {
    setSelectedRun(null);
    refresh().catch((error) => setMessage(error.message));
  }, [projectId]);

  async function inspectRun(runId) {
    setBusy(true);
    try {
      setSelectedRun(await apiFetch(`/projects/${projectId}/analytics/runs/${runId}`, { force: true }));
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function savePrivacy(field, checked) {
    const next = { ...analytics.settings, [field]: checked };
    setAnalytics({ ...analytics, settings: next });
    try {
      await apiFetch(`/projects/${projectId}/analytics/settings`, {
        method: "PATCH",
        body: JSON.stringify(next),
      });
      setMessage("Telemetry privacy settings saved.");
    } catch (error) {
      setMessage(error.message);
    }
  }

  async function replayRun() {
    if (!selectedRun) return;
    setBusy(true);
    try {
      const result = await apiFetch(`/projects/${projectId}/analytics/runs/${selectedRun.id}/replay`, { method: "POST" });
      setMessage(`Replay queued as job ${result.job?.id?.slice(0, 8) || ""}.`);
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function exportDiagnostics() {
    setBusy(true);
    try {
      const result = await apiFetch(`/projects/${projectId}/diagnostics/export`, {
        method: "POST",
        body: JSON.stringify(diagnosticsOptions),
      });
      setMessage(`Diagnostics export queued as job ${result.job?.id?.slice(0, 8) || ""}.`);
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function previewDiagnostics() {
    setBusy(true);
    try {
      const query = new URLSearchParams({
        include_logs: String(diagnosticsOptions.include_logs),
        include_recent_errors: String(diagnosticsOptions.include_recent_errors),
        include_traces: String(diagnosticsOptions.include_traces),
        log_line_limit: String(diagnosticsOptions.log_line_limit),
        redaction_profile: diagnosticsOptions.redaction_profile,
      });
      const result = await apiFetch(`/projects/${projectId}/diagnostics/preview?${query.toString()}`, { force: true });
      setDiagnosticsPreview(result);
      setMessage("Diagnostics redaction preview refreshed.");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  function updateDiagnosticsOption(field, value) {
    setDiagnosticsOptions((current) => ({ ...current, [field]: value }));
    setDiagnosticsPreview(null);
  }

  async function cancelJob(jobId) {
    setBusy(true);
    try {
      await apiFetch(`/projects/${projectId}/jobs/${jobId}/cancel`, { method: "POST" });
      setMessage("Job cancellation requested.");
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function retryJob(jobId) {
    setBusy(true);
    try {
      await apiFetch(`/projects/${projectId}/jobs/${jobId}/retry`, { method: "POST" });
      setMessage("Job retry queued.");
      await refresh();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  if (!analytics) return <div className="project-loading-state"><strong>Loading project analytics...</strong></div>;
  const totals = analytics.totals || {};
  const mostExpensive = analytics.by_workflow?.[0];
  const recentJobs = health?.jobs?.recent || [];
  const recentRuns = analytics.recent_runs || [];
  const hasModelActivity = Number(totals.calls || 0) > 0;
  const hasRecentJobs = recentJobs.length > 0;
  const hasRecentRuns = recentRuns.length > 0;
  const hasFailures = Number(totals.failures || 0) > 0 || Number(totals.timeouts || 0) > 0 || Boolean(health?.jobs?.last_error);
  const quietState = !hasModelActivity && !hasRecentJobs && !hasRecentRuns && !hasFailures;

  return (
    <div className="analytics-workspace">
      <div className={`analytics-hero panel${quietState ? " analytics-hero-quiet" : ""}`}>
        <div>
          <h2>{quietState ? "Local stack healthy and quiet" : `${formatNumber(totals.total_tokens)} tokens across ${formatNumber(totals.calls)} model calls`}</h2>
          <p className="muted">
            {quietState
              ? "No recent model calls or queued jobs for this project. Use Analytics when you need to inspect runtime health, failures, or diagnostics."
              : `${Number(totals.generation_seconds || 0).toFixed(1)} seconds of generation.${mostExpensive ? ` Highest-usage workflow: ${mostExpensive.name}.` : ""}`}
          </p>
        </div>
        <div className="button-row">
          <button type="button" className="secondary-button" onClick={refresh}>Refresh</button>
          <button type="button" onClick={exportDiagnostics} disabled={busy}>Export Diagnostics</button>
        </div>
      </div>

      {message ? <div className="status-banner">{message}</div> : null}

      {hasModelActivity ? (
        <>
          <div className="analytics-metrics">
            <Metric label="Estimated cost" value={formatCost(totals.estimated_cost_usd)} detail="Local calls remain $0" />
            <Metric label="Local / remote" value={`${formatNumber(totals.local_calls)} / ${formatNumber(totals.remote_calls)}`} />
            <Metric label="Failures / timeouts" value={`${formatNumber(totals.failures)} / ${formatNumber(totals.timeouts)}`} />
            <Metric label="Average latency" value={`${formatNumber(totals.average_latency_ms)} ms`} />
            <Metric label="Retries" value={formatNumber(totals.retries)} />
          </div>

          <div className="analytics-grid">
            <Breakdown title="By layer" rows={analytics.by_layer} />
            <Breakdown title="By model" rows={analytics.by_model} />
            <Breakdown title="By workflow" rows={analytics.by_workflow} />
          </div>
        </>
      ) : null}

      <div className="analytics-grid analytics-lower-grid">
        <div className="panel">
          <h3>Background and platform health</h3>
          <div className="health-list">
            <span><strong>Database</strong> {health?.database?.ok ? "Healthy" : "Unavailable"}</span>
            <span><strong>Model server</strong> {health?.model_server?.ok ? "Ready" : "Offline"}</span>
            <span><strong>Embeddings</strong> {formatNumber(health?.pgvector?.embedding_count)}</span>
            <span><strong>Jobs</strong> {formatNumber(health?.jobs?.running)} running, {formatNumber(health?.jobs?.queued)} queued, {formatNumber(health?.jobs?.failed)} failed</span>
            {health?.jobs?.last_error ? <span className="warning"><strong>Last error</strong> {health.jobs.last_error}</span> : null}
          </div>
        </div>

        <details className="panel analytics-collapsible">
          <summary>Privacy and retention</summary>
          <div className="analytics-collapsible-body">
            <label className="checkbox-item"><input type="checkbox" checked={analytics.settings.enabled} onChange={(event) => savePrivacy("enabled", event.target.checked)} /> Capture telemetry</label>
            <label className="checkbox-item"><input type="checkbox" checked={analytics.settings.capture_prompt_bodies} onChange={(event) => savePrivacy("capture_prompt_bodies", event.target.checked)} /> Retain prompt bodies</label>
            <label className="checkbox-item"><input type="checkbox" checked={analytics.settings.capture_response_bodies} onChange={(event) => savePrivacy("capture_response_bodies", event.target.checked)} /> Retain raw responses</label>
            <label className="checkbox-item"><input type="checkbox" checked={analytics.settings.capture_parsed_results} onChange={(event) => savePrivacy("capture_parsed_results", event.target.checked)} /> Retain parsed results</label>
            <p className="muted">Changes affect future calls. Existing retained content is not rewritten.</p>
          </div>
        </details>
      </div>

      {hasRecentJobs || hasFailures ? (
        <JobQueue jobs={recentJobs} onCancel={cancelJob} onRetry={retryJob} busy={busy} />
      ) : (
        <div className="panel analytics-empty-panel">
          <h3>Unified job queue</h3>
          <p className="muted">No queued, running, or failed jobs for this project right now.</p>
        </div>
      )}

      <details className="panel diagnostics-panel analytics-collapsible">
        <summary>Diagnostics bundle</summary>
        <div className="analytics-collapsible-body">
          <div className="panel-header">
            <div>
              <p className="muted">Preview redaction before creating a support export.</p>
            </div>
            <div className="button-row">
              <button type="button" className="secondary-button" onClick={previewDiagnostics} disabled={busy}>Preview</button>
              <button type="button" onClick={exportDiagnostics} disabled={busy}>Export</button>
            </div>
          </div>
          <div className="diagnostics-options">
            <label className="checkbox-item"><input type="checkbox" checked={diagnosticsOptions.include_logs} onChange={(event) => updateDiagnosticsOption("include_logs", event.target.checked)} /> Logs</label>
            <label className="checkbox-item"><input type="checkbox" checked={diagnosticsOptions.include_recent_errors} onChange={(event) => updateDiagnosticsOption("include_recent_errors", event.target.checked)} /> Recent errors</label>
            <label className="checkbox-item"><input type="checkbox" checked={diagnosticsOptions.include_traces} onChange={(event) => updateDiagnosticsOption("include_traces", event.target.checked)} /> Traces</label>
            <label>Log lines <input type="number" min="1" max="1000" value={diagnosticsOptions.log_line_limit} onChange={(event) => updateDiagnosticsOption("log_line_limit", Number(event.target.value || 1))} /></label>
            <label>Redaction <select value={diagnosticsOptions.redaction_profile} onChange={(event) => updateDiagnosticsOption("redaction_profile", event.target.value)}>
              <option value="standard">Standard</option>
            </select></label>
          </div>
          {diagnosticsPreview ? (
            <div className="diagnostics-preview">
              <div className="analytics-row">
                <strong>Bundle v{diagnosticsPreview.manifest?.bundle_version}</strong>
                <span data-label="Schema">{diagnosticsPreview.manifest?.bundle_schema_id}</span>
                <span data-label="Hash">{diagnosticsPreview.manifest?.content_hash?.slice(0, 12)}</span>
                <span data-label="Redactions">{Object.values(diagnosticsPreview.manifest?.redaction?.replacement_counts || {}).reduce((sum, count) => sum + count, 0)} redactions</span>
                <span data-label="Sections">{diagnosticsPreview.sections?.length || 0} sections</span>
              </div>
              <pre>{JSON.stringify({
                sections: diagnosticsPreview.sections?.map((section) => ({ name: section.name, count: section.count })),
                redactions: diagnosticsPreview.manifest?.redaction?.replacement_counts,
                warnings: diagnosticsPreview.manifest?.warnings,
              }, null, 2)}</pre>
            </div>
          ) : <p className="muted">Run preview to inspect included sections and redaction counts.</p>}
        </div>
      </details>

      {hasRecentRuns || selectedRun ? (
        <div className="panel">
          <h3>Run inspector</h3>
          <div className="run-list">
            {recentRuns.map((run) => (
              <button type="button" key={run.id} className="run-row" onClick={() => inspectRun(run.id)}>
                <span className={`status-pill ${run.status}`} data-label="Status">{run.status}</span>
                <strong>{run.workflow}</strong>
                <span data-label="Layer">{run.layer}</span>
                <span data-label="Model">{run.model_name || "unknown model"}</span>
                <span data-label="Tokens">{formatNumber(run.total_tokens)} tokens</span>
                <span data-label="Latency">{formatNumber(run.latency_ms)} ms</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {selectedRun ? (
        <div className="panel run-inspector">
          <div className="panel-header">
            <div>
              <h3>{selectedRun.workflow}</h3>
              <p className="muted">Prompt version {selectedRun.prompt_version || "not recorded"} | {selectedRun.model_profile_id || selectedRun.model_name}</p>
            </div>
            <button type="button" onClick={replayRun} disabled={busy || !selectedRun.user_prompt}>Replay Run</button>
          </div>
          {selectedRun.error_message ? <div className="error-banner">{selectedRun.error_type}: {selectedRun.error_message}</div> : null}
          <details><summary>System prompt</summary><pre>{selectedRun.system_prompt || "Redacted by telemetry settings."}</pre></details>
          <details><summary>User prompt</summary><pre>{selectedRun.user_prompt || "Redacted by telemetry settings."}</pre></details>
          <details open><summary>Parsed result</summary><pre>{JSON.stringify(selectedRun.parsed_result || {}, null, 2)}</pre></details>
          <details><summary>Raw response</summary><pre>{selectedRun.raw_response || "Redacted by telemetry settings."}</pre></details>
          <details><summary>Request metadata</summary><pre>{JSON.stringify(selectedRun.metadata || {}, null, 2)}</pre></details>
        </div>
      ) : null}
    </div>
  );
}
