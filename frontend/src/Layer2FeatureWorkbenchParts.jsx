import { useEffect, useState } from "react";
import { COVERAGE_STATUSES, FEATURE_STATUSES, GRANULARITY_CLASSES, splitLines } from "./layer2WorkbenchUtils";
import "./Layer2GraphPanel.css";

export function Layer2FeatureForm({ pillars, onCreate, defaultOwnerId = "" }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    canonical_name: "",
    description: "",
    owner_pillar_id: defaultOwnerId || pillars[0]?.id || "",
    feature_type: "capability",
    granularity_class: "feature",
    coverage_family: "",
    aliases: "",
    status: "candidate",
    priority: "",
    notes: "",
  });

  useEffect(() => {
    setForm((current) => {
      if (defaultOwnerId && current.owner_pillar_id !== defaultOwnerId) {
        return { ...current, owner_pillar_id: defaultOwnerId };
      }
      if (current.owner_pillar_id || !pillars[0]?.id) {
        return current;
      }
      return { ...current, owner_pillar_id: pillars[0].id };
    });
  }, [pillars, defaultOwnerId]);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    if (!onCreate) return;
    await onCreate({ ...form, aliases: splitLines(form.aliases) });
    setForm({ ...form, canonical_name: "", description: "", aliases: "", notes: "" });
    setOpen(false);
  }

  if (!open) {
    return <button type="button" onClick={() => setOpen(true)}>Add feature</button>;
  }

  return (
    <form className="layer2-workbench-form" onSubmit={submit}>
      <div className="layer2-form-head">
        <div>
          <h4>Add Layer 2 feature</h4>
          <p className="muted">Create a concrete capability under a kept pillar without running generation.</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => setOpen(false)}>Close</button>
      </div>
      <div className="brief-grid">
        <label>
          Feature name
          <input value={form.canonical_name} onChange={(event) => update("canonical_name", event.target.value)} required />
        </label>
        <label>
          Owner pillar
          <select value={form.owner_pillar_id} onChange={(event) => update("owner_pillar_id", event.target.value)} required>
            {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
          </select>
        </label>
        <label>
          Type
          <input value={form.feature_type} onChange={(event) => update("feature_type", event.target.value)} />
        </label>
        <label>
          Granularity
          <select value={form.granularity_class} onChange={(event) => update("granularity_class", event.target.value)}>
            {GRANULARITY_CLASSES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Coverage family
          <input value={form.coverage_family} onChange={(event) => update("coverage_family", event.target.value)} />
        </label>
        <label>
          Status
          <select value={form.status} onChange={(event) => update("status", event.target.value)}>
            {FEATURE_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      </div>
      <label>
        Description
        <textarea value={form.description} onChange={(event) => update("description", event.target.value)} rows={3} required />
      </label>
      <label>
        Aliases
        <textarea value={form.aliases} onChange={(event) => update("aliases", event.target.value)} rows={3} />
      </label>
      <label>
        Notes
        <textarea value={form.notes} onChange={(event) => update("notes", event.target.value)} rows={3} />
      </label>
      <div className="button-row">
        <button type="submit" disabled={!form.canonical_name.trim() || !form.description.trim() || !form.owner_pillar_id}>Save feature</button>
        <button type="button" className="secondary-button" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}

export function FeatureDetail({ feature, pillars, onUpdate, onReview, onAddEvidence }) {
  const [form, setForm] = useState(feature);
  const [evidence, setEvidence] = useState({
    competitor_name: "",
    coverage_status: "unclear",
    confidence: 50,
    source_url: "",
    evidence_snippet: "",
    notes: "",
    source_type: "manual",
  });

  useEffect(() => {
    setForm(feature);
  }, [feature]);

  if (!feature || !form) return <p className="muted">Select a feature to inspect it.</p>;

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function save() {
    if (!onUpdate) return;
    await onUpdate(feature.id, {
      canonical_name: form.canonical_name,
      description: form.description,
      feature_type: form.feature_type,
      granularity_class: form.granularity_class,
      owner_pillar_id: form.owner_pillar_id,
      status: form.status,
      coverage_family: form.coverage_family || "",
      priority: form.priority || "",
      notes: form.notes || "",
    });
  }

  async function addEvidence(event) {
    event.preventDefault();
    if (!onAddEvidence) return;
    await onAddEvidence({ ...evidence, feature_id: feature.id, confidence: Number(evidence.confidence) });
    setEvidence({ ...evidence, competitor_name: "", source_url: "", evidence_snippet: "", notes: "" });
  }

  return (
    <div className="layer2-detail">
      <div className="panel-header">
        <div>
          <h3>{feature.canonical_name}</h3>
          <p className="muted">{feature.description || "No description yet."}</p>
        </div>
        <div className="layer2-detail-state">
          <span className={`status-pill ${feature.status}`}>{feature.status}</span>
          {feature.layer3_ready ? <span className="status-pill published">Approved</span> : null}
        </div>
      </div>
      <div className="brief-grid">
        <label>
          Name
          <input value={form.canonical_name || ""} onChange={(event) => update("canonical_name", event.target.value)} />
        </label>
        <label>
          Owner
          <select value={form.owner_pillar_id || ""} onChange={(event) => update("owner_pillar_id", event.target.value)}>
            {pillars.map((pillar) => <option key={pillar.id} value={pillar.id}>{pillar.title}</option>)}
          </select>
        </label>
        <label>
          Status
          <select value={form.status || "candidate"} onChange={(event) => update("status", event.target.value)}>
            {FEATURE_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Granularity
          <select value={form.granularity_class || "feature"} onChange={(event) => update("granularity_class", event.target.value)}>
            {GRANULARITY_CLASSES.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Type
          <input value={form.feature_type || ""} onChange={(event) => update("feature_type", event.target.value)} />
        </label>
        <label>
          Coverage family
          <input value={form.coverage_family || ""} onChange={(event) => update("coverage_family", event.target.value)} />
        </label>
      </div>
      <label>
        Description
        <textarea value={form.description || ""} onChange={(event) => update("description", event.target.value)} rows={4} />
      </label>
      <label>
        Notes
        <textarea value={form.notes || ""} onChange={(event) => update("notes", event.target.value)} rows={3} />
      </label>
      <div className="button-row">
        <button type="button" onClick={save} disabled={!onUpdate}>Save feature</button>
        <button type="button" className="secondary-button" onClick={() => onReview?.({ action_type: "approve_for_layer3", feature_id: feature.id })} disabled={!onReview}>Accept</button>
        <button type="button" className="secondary-button" onClick={() => onReview?.({ action_type: "cut", feature_id: feature.id })} disabled={!onReview}>Reject</button>
      </div>
      <div className="layer2-score-grid">
        <span>Fit {feature.pillar_fit_score}/100</span>
        <span>Distinct {feature.distinctiveness_score}/100</span>
        <span>Strategic {feature.strategic_value_score}/100</span>
        <span>Leakage {feature.implementation_leakage_score}/100</span>
        <span>Competitor {feature.competitor_coverage_score || 0}%</span>
        <span>{feature.layer3_ready ? "Approved" : `Blocked: ${(feature.readiness_blockers || []).join(", ")}`}</span>
      </div>
      <form className="layer2-evidence-form" onSubmit={addEvidence}>
        <div className="layer2-form-head">
          <div>
            <h4>Manual competitor evidence</h4>
            <p className="muted">Attach a source-backed signal to this feature.</p>
          </div>
        </div>
        <div className="brief-grid">
          <label>
            Competitor
            <input value={evidence.competitor_name} onChange={(event) => setEvidence({ ...evidence, competitor_name: event.target.value })} required />
          </label>
          <label>
            Coverage
            <select value={evidence.coverage_status} onChange={(event) => setEvidence({ ...evidence, coverage_status: event.target.value })}>
              {COVERAGE_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Confidence
            <input type="number" min="0" max="100" value={evidence.confidence} onChange={(event) => setEvidence({ ...evidence, confidence: event.target.value })} />
          </label>
          <label>
            Source URL
            <input value={evidence.source_url} onChange={(event) => setEvidence({ ...evidence, source_url: event.target.value })} />
          </label>
        </div>
        <label>
          Evidence
          <textarea value={evidence.evidence_snippet} onChange={(event) => setEvidence({ ...evidence, evidence_snippet: event.target.value })} rows={3} />
        </label>
        <label>
          Notes
          <textarea value={evidence.notes} onChange={(event) => setEvidence({ ...evidence, notes: event.target.value })} rows={2} />
        </label>
        <button type="submit" disabled={!onAddEvidence || !evidence.competitor_name.trim()}>Add evidence</button>
      </form>
      {feature.evidence?.length ? (
        <ul className="summary-list layer2-evidence-list">
          {feature.evidence.map((item) => (
            <li key={item.id}>
              <strong>{item.competitor_name}: {item.coverage_status}</strong>
              <span>confidence {item.confidence}/100 | {item.source_type}</span>
              {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">source</a> : null}
              {item.rationale ? <p>{item.rationale}</p> : null}
              {item.evidence_snippet ? <p className="muted">{item.evidence_snippet}</p> : null}
            </li>
          ))}
        </ul>
      ) : <p className="muted">No feature evidence yet.</p>}
    </div>
  );
}
