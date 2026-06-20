import { useEffect, useState } from "react";

// Renders a reusable checkbox group for selecting nodes before generation.
export function CheckboxList({ title, options, selectedValues, onChange }) {
  const entries = Object.entries(options);
  if (!entries.length) {
    return <p className="muted">No eligible items yet.</p>;
  }
  return (
    <div className="panel">
      <h3>{title}</h3>
      <div className="checkbox-grid">
        {entries.map(([label, value]) => (
          <label key={value} className="checkbox-item">
            <input
              type="checkbox"
              checked={selectedValues.includes(value)}
              onChange={(event) => {
                if (event.target.checked) {
                  onChange([...selectedValues, value]);
                  return;
                }
                onChange(selectedValues.filter((item) => item !== value));
              }}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

// Render node review controls and push edits back through the API.
export function NodeEditor({ node, onSave, findings, onRerunResearch }) {
  const [title, setTitle] = useState(node.title);
  const [description, setDescription] = useState(node.description || "");
  const [status, setStatus] = useState(node.status);
  const [priority, setPriority] = useState(node.priority ?? 0);
  const duplicate = node.json_payload?.possible_duplicate;
  const assessment = node.json_payload?.pillar_assessment;
  const semanticSimilarity = node.json_payload?.semantic_similarity;

  // Keep local form state aligned with server-refreshed node payloads.
  useEffect(() => {
    setTitle(node.title);
    setDescription(node.description || "");
    setStatus(node.status);
    setPriority(node.priority ?? 0);
  }, [node]);

  return (
    <div className="panel">
      <div className="panel-header">
        <h3>{node.title}</h3>
        <span>{node.node_type}</span>
      </div>
      {duplicate ? (
        <p className="warning">
          Possible duplicate of {duplicate.duplicate_title} (title {duplicate.title_score} / description {duplicate.description_score})
        </p>
      ) : null}
      {semanticSimilarity?.matches?.length ? (
        <div className="warning">
          <p>Embedding overlap detected. Top cosine similarity: {semanticSimilarity.top_score}</p>
          <ul className="summary-list">
            {semanticSimilarity.matches.map((match) => (
              <li key={match.node_id}>
                {match.title} | score {match.score} | layer {match.layer} | type {match.node_type}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {assessment ? (
        <div className="meta-block">
          <p>Canonical: {assessment.canonical_title || node.title}</p>
          <p>
            Quality {assessment.pillar_quality_score}/100 | Distinctiveness {assessment.distinctiveness_score}/100 | Strategic value{" "}
            {assessment.strategic_value_score}/100
          </p>
        </div>
      ) : null}
      <label>
        Title
        <input value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>
        Description
        <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={4} />
      </label>
      <div className="field-row">
        <label>
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="generated">generated</option>
            <option value="kept">kept</option>
            <option value="cut">cut</option>
            <option value="merged">merged</option>
            <option value="prioritized">prioritized</option>
          </select>
        </label>
        <label>
          Priority
          <input
            type="number"
            min="0"
            max="10"
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
          />
        </label>
      </div>
      <button
        type="button"
        onClick={() =>
          onSave(node.id, {
            title,
            description,
            status,
            priority,
          })
        }
      >
        Save
      </button>
      <CoverageMatrix node={node} findings={findings} onRerun={onRerunResearch} />
    </div>
  );
}

// Render the summary returned by a generation pass.
export function GenerationSummary({ summary }) {
  if (!summary) {
    return null;
  }
  return (
    <div className="panel">
      <h3>Last Generation Result</h3>
      <p>Stop reason: {summary.stop_reason}</p>
      <p>Rounds: {summary.total_rounds}</p>
      <p>New items: {summary.created_nodes?.length || 0}</p>
      <p>Duplicates skipped: {summary.duplicate_candidates}</p>
      <p>Filtered skipped: {summary.filtered_candidates}</p>
      <p>Thinking mode: {summary.thinking_enabled ? "on" : "off"}</p>
      {summary.final_coverage_summary ? <p>{summary.final_coverage_summary}</p> : null}
      {summary.round_summaries?.length ? (
        <ul className="summary-list">
          {summary.round_summaries.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ResearchStatus({ jobs, onRerunLayer0, onRerunLayer1 }) {
  // Shows recent background research activity and manual rerun controls.
  const recent = jobs.slice(0, 8);
  return (
    <div className="panel">
      <div className="panel-header">
        <h3>Research Status</h3>
        <div className="button-row">
          <button type="button" onClick={onRerunLayer0}>Rerun Layer 0</button>
          <button type="button" onClick={() => onRerunLayer1([])}>Rerun Layer 1</button>
        </div>
      </div>
      {recent.length ? (
        <div className="status-grid">
          {recent.map((job) => (
            <div key={job.id} className={`status-card ${job.status}`}>
              <strong>{job.job_type}</strong>
              <span>{job.scope}{job.scope_id ? ` | ${job.scope_id.slice(0, 8)}` : ""}</span>
              <span>{job.status} | {job.progress}%</span>
              {job.error ? <span className="warning-text">{job.error}</span> : null}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No research jobs yet.</p>
      )}
    </div>
  );
}

export function MarketPanel({ findings }) {
  // Summarizes Layer 0 competitor research once the brief has been published.
  const landscape = findings.find((finding) => finding.scope === "layer0" && finding.finding_type === "market_landscape");
  if (!landscape) {
    return (
      <div className="panel">
        <h3>Layer 0 Market</h3>
        <p className="muted">Publish the brief to start local competitor research.</p>
      </div>
    );
  }
  const payload = landscape.payload || {};
  return (
    <div className="panel">
      <h3>Layer 0 Market</h3>
      <p>{landscape.summary}</p>
      <div className="info-grid">
        <div>
          <strong>Themes</strong>
          <p>{(payload.major_capability_themes || []).join(", ") || "Unclear"}</p>
        </div>
        <div>
          <strong>Saturation</strong>
          <p>{payload.market_saturation_notes || "Unclear"}</p>
        </div>
        <div>
          <strong>Whitespace</strong>
          <p>{payload.whitespace_opportunity_notes || "Unclear"}</p>
        </div>
      </div>
      <ul className="summary-list">
        {(payload.evidence || []).slice(0, 6).map((item) => (
          <li key={`${item.url}-${item.snippet}`}>
            <a href={item.url} target="_blank" rel="noreferrer">{item.competitor_name}</a>: {item.snippet}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CoverageMatrix({ node, findings, onRerun }) {
  // Shows Layer 1 competitor coverage evidence directly under the reviewed pillar.
  if (node.node_type !== "pillar" || node.layer !== 1) {
    return null;
  }
  const finding = findings.find((item) => item.scope === "layer1" && item.scope_id === node.id && item.finding_type === "pillar_coverage_matrix");
  const matrix = finding?.payload?.matrix || [];
  const profile = finding?.payload?.engineering_profile || null;
  return (
    <div className="coverage-box">
      <div className="panel-header">
        <strong>Competitor Coverage</strong>
        <button type="button" onClick={() => onRerun([node.id])}>Rerun</button>
      </div>
      {profile ? (
        <div className="research-scorecard">
          <div className="research-scorecard-head">
            <strong>Implementation profile</strong>
            <div className="research-scorecard-head-meta">
              <span className="status-pill">confidence {profile.confidence}/100</span>
              <span className="research-index-pill">indexed score {profile.indexed_score ?? 0}/100</span>
            </div>
          </div>
          <p className="research-scorecard-summary">{profile.summary}</p>
          <div className="research-rating-grid">
            {(profile.ratings || []).map((rating) => (
              <div key={rating.name} className="research-rating-card">
                <span>{rating.label}</span>
                <strong>{rating.rating}/10</strong>
                <p>{rating.rationale}</p>
              </div>
            ))}
          </div>
          {profile.implications?.length ? (
            <ul className="summary-list">
              {profile.implications.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : null}
        </div>
      ) : null}
      {node.json_payload?.research_stale ? <p className="warning">Research is stale for this edited pillar.</p> : null}
      {matrix.length ? (
        <div className="matrix-table">
          <div className="matrix-row matrix-head">
            <span>Competitor</span>
            <span>Status</span>
            <span>Adoption</span>
            <span>Confidence</span>
          </div>
          {matrix.map((row) => (
            <div key={row.competitor_name} className="matrix-row">
              <span>{row.competitor_name}</span>
              <span>{row.coverage_status}</span>
              <span>{row.adoption_level}</span>
              <span>{row.confidence}</span>
              <p>{row.whitespace_note}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No pillar research finding yet.</p>
      )}
    </div>
  );
}

