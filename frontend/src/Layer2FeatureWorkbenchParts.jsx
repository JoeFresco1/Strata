import { useEffect, useState } from "react";
import { COVERAGE_STATUSES, FEATURE_STATUSES, GRANULARITY_CLASSES, splitLines } from "./layer2WorkbenchUtils";

export function Layer2FeatureForm({ pillars, onCreate }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    canonical_name: "",
    description: "",
    owner_pillar_id: pillars[0]?.id || "",
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
      if (current.owner_pillar_id || !pillars[0]?.id) {
        return current;
      }
      return { ...current, owner_pillar_id: pillars[0].id };
    });
  }, [pillars]);

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
    return <button type="button" onClick={() => setOpen(true)}>Add Feature</button>;
  }

  return (
    <form className="layer2-workbench-form" onSubmit={submit}>
      <div className="brief-grid">
        <label>
          Feature Name
          <input value={form.canonical_name} onChange={(event) => update("canonical_name", event.target.value)} required />
        </label>
        <label>
          Owner Pillar
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
          Coverage Family
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
        <button type="submit" disabled={!form.canonical_name.trim() || !form.description.trim() || !form.owner_pillar_id}>Save Feature</button>
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
        <h3>{feature.canonical_name}</h3>
        <span className={`status-pill ${feature.status}`}>{feature.status}</span>
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
          Coverage Family
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
        <button type="button" onClick={save} disabled={!onUpdate}>Save Feature</button>
        <button type="button" className="secondary-button" onClick={() => onReview?.({ action_type: "approve_for_layer3", feature_id: feature.id })} disabled={!onReview}>Approve</button>
        <button type="button" className="secondary-button" onClick={() => onReview?.({ action_type: "cut", feature_id: feature.id })} disabled={!onReview}>Cut</button>
      </div>
      <div className="layer2-score-grid">
        <span>Fit {feature.pillar_fit_score}/100</span>
        <span>Distinct {feature.distinctiveness_score}/100</span>
        <span>Strategic {feature.strategic_value_score}/100</span>
        <span>Leakage {feature.implementation_leakage_score}/100</span>
        <span>Competitor {feature.competitor_coverage_score || 0}%</span>
        <span>{feature.layer3_ready ? "Layer 3 ready" : `Blocked: ${(feature.readiness_blockers || []).join(", ")}`}</span>
      </div>
      <form className="layer2-evidence-form" onSubmit={addEvidence}>
        <h4>Manual Competitor Evidence</h4>
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
        <button type="submit" disabled={!onAddEvidence}>Add Evidence</button>
      </form>
      {feature.evidence?.length ? (
        <ul className="summary-list">
          {feature.evidence.map((item) => (
            <li key={item.id}>
              {item.competitor_name}: {item.coverage_status} | confidence {item.confidence}/100
              {item.source_url ? <> | <a href={item.source_url} target="_blank" rel="noreferrer">source</a></> : null}
            </li>
          ))}
        </ul>
      ) : <p className="muted">No feature evidence yet.</p>}
    </div>
  );
}
