import { useMemo, useState } from "react";
import WorkspaceJobNotice from "./workspace/WorkspaceJobNotice";

const SECTIONS = [
  ["overview", "Overview"],
  ["lenses", "Lenses"],
  ["actors", "Actors"],
  ["lifecycle_stages", "Lifecycle"],
  ["domains", "Product domains"],
  ["enterprise_obligations", "Enterprise obligations"],
  ["cross_domain_opportunities", "Cross-domain opportunities"],
  ["competitor_research", "Competitor research"],
  ["coverage_risks", "Coverage risks"],
  ["open_questions", "Open questions"],
  ["revision_history", "Revision history"],
];

function formatDate(value) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not available" : date.toLocaleString();
}

function sourceLabel(item) {
  return {
    baseline: "Baseline policy",
    model_discovered: "Model generated",
    competitor_research: "Competitor research",
    human_added: "Human authored",
  }[item?.source] || "Model generated";
}

function EmptySection({ title }) {
  return (
    <div className="discovery-section-empty">
      <strong>No {title.toLowerCase()} yet</strong>
      <span>This section will remain inspectable after a discovery candidate is generated.</span>
    </div>
  );
}

function ItemList({ title, items, renderMeta, renderActions }) {
  if (!items?.length) return <EmptySection title={title} />;
  return (
    <div className="discovery-item-list">
      {items.map((item) => (
        <article className="discovery-item-card" key={item.id}>
          <div className="discovery-item-head">
            <div>
              <span className={`discovery-source ${item.source || "model_discovered"}`}>{sourceLabel(item)}</span>
              <h4>{item.title || item.question || item.name || "Untitled item"}</h4>
            </div>
            {item.recommendation || item.downstream_state ? (
              <span className={`status-pill ${item.downstream_state || item.recommendation}`}>
                {item.downstream_state || item.recommendation}
              </span>
            ) : null}
          </div>
          <p>{item.description || item.why_it_matters || item.question || "No description supplied."}</p>
          {renderMeta ? renderMeta(item) : null}
          {renderActions ? <div className="discovery-inline-actions">{renderActions(item)}</div> : null}
        </article>
      ))}
    </div>
  );
}

function CompetitorResearchSection({
  discovery,
  researchJobState,
  onStartResearch,
  onResearchAction,
  onResearchEdit,
  onAttachResearch,
  onCancelJob,
}) {
  const research = discovery?.competitor_research || {};
  const latest = research.current_candidate || research.published || research.revisions?.at(-1);
  const [mode, setMode] = useState(discovery?.current_candidate?.competitor_research_mode || "no_competitor_research");
  const [competitors, setCompetitors] = useState("");
  const [sourceBudget, setSourceBudget] = useState(12);
  const [timeBudget, setTimeBudget] = useState(120);
  const [maxCompetitors, setMaxCompetitors] = useState(4);
  const [perCompetitorLimit, setPerCompetitorLimit] = useState(3);
  const [approvedSecondarySources, setApprovedSecondarySources] = useState(false);
  const [competitorToAdd, setCompetitorToAdd] = useState("");
  const running = ["queued", "running"].includes(researchJobState?.state);

  function start() {
    if (mode === "no_competitor_research") return;
    onStartResearch({
      mode,
      competitor_names: competitors.split("\n").map((item) => item.trim()).filter(Boolean),
      source_budget: Number(sourceBudget),
      time_budget_seconds: Number(timeBudget),
      max_competitors: Number(maxCompetitors),
      per_competitor_source_limit: Number(perCompetitorLimit),
      approved_secondary_sources: approvedSecondarySources,
    });
  }

  function chooseMode(value) {
    setMode(value);
    if (value === "deep_competitor_research") {
      setMaxCompetitors(8);
      setSourceBudget(40);
      setTimeBudget(600);
      setPerCompetitorLimit(8);
    } else if (value === "lightweight_competitor_scan") {
      setMaxCompetitors(4);
      setSourceBudget(12);
      setTimeBudget(120);
      setPerCompetitorLimit(3);
      setApprovedSecondarySources(false);
    }
  }

  return (
    <section className="discovery-content-section">
      <div className="discovery-section-head">
        <div>
          <span className="workspace-eyebrow">Optional and independently versioned</span>
          <h3>Competitor research</h3>
          <p className="muted">Research never starts unless you choose a mode and start it here. Discovery can finish without it.</p>
        </div>
      </div>
      <div className="competitor-mode-grid">
        {[
          ["no_competitor_research", "No research", "Use only the published brief and your own notes."],
          ["lightweight_competitor_scan", "Lightweight scan", "Bounded first-party scan for major territories and table stakes."],
          ["deep_competitor_research", "Deep research", "Checkpointed evidence and inferred competitor territories."],
        ].map(([value, label, description]) => (
          <label className={`competitor-mode-card${mode === value ? " selected" : ""}`} key={value}>
            <input type="radio" name="competitor-mode" value={value} checked={mode === value} onChange={() => chooseMode(value)} />
            <strong>{label}</strong>
            <span>{description}</span>
          </label>
        ))}
      </div>
      {mode !== "no_competitor_research" ? (
        <div className="competitor-scope-form">
          <label>
            <span>Competitors, one per line</span>
            <textarea value={competitors} onChange={(event) => setCompetitors(event.target.value)} placeholder="Use brief competitors when left empty" />
          </label>
          <label>
            <span>Maximum competitors</span>
            <input type="number" min="1" max="50" value={maxCompetitors} onChange={(event) => setMaxCompetitors(event.target.value)} />
          </label>
          <label>
            <span>Source budget</span>
            <input type="number" min="1" max="1000" value={sourceBudget} onChange={(event) => setSourceBudget(event.target.value)} />
          </label>
          <label>
            <span>Time budget (seconds)</span>
            <input type="number" min="1" max="86400" value={timeBudget} onChange={(event) => setTimeBudget(event.target.value)} />
          </label>
          <label>
            <span>Sources per competitor</span>
            <input type="number" min="1" max="200" value={perCompetitorLimit} onChange={(event) => setPerCompetitorLimit(event.target.value)} />
          </label>
          {mode === "deep_competitor_research" ? (
            <label className="checkbox-item">
              <input type="checkbox" checked={approvedSecondarySources} onChange={(event) => setApprovedSecondarySources(event.target.checked)} />
              Allow approved secondary sources
            </label>
          ) : null}
          <button type="button" onClick={start} disabled={running}>{running ? "Research running" : "Start competitor research"}</button>
        </div>
      ) : (
        <div className="brief-editor-notice">
          <strong>Competitor coverage will be marked not evaluated</strong>
          <span>Core Product Discovery remains available and will not wait for external research.</span>
        </div>
      )}
      <WorkspaceJobNotice jobState={researchJobState} label="Competitor research" onCancel={onCancelJob} />
      {latest ? (
        <div className="discovery-research-result">
          <div className="discovery-item-head">
            <div>
              <span className="workspace-eyebrow">Revision {latest.revision_number}</span>
              <h4>{latest.scope?.mode?.replaceAll("_", " ")}</h4>
            </div>
            <span className={`status-pill ${latest.state}`}>{latest.state}</span>
          </div>
          <dl className="discovery-metrics">
            <div><dt>Competitors</dt><dd>{latest.profiles?.length || 0}</dd></div>
            <div><dt>Evidence records</dt><dd>{latest.evidence?.length || 0}</dd></div>
            <div><dt>Inferred pillars</dt><dd>{latest.inferred_pillars?.length || 0}</dd></div>
            <div><dt>Freshness</dt><dd>{latest.freshness_state}</dd></div>
            <div><dt>Completed</dt><dd>{latest.checkpoint_state?.completed_competitor_ids?.length || 0}</dd></div>
            <div><dt>Unresolved</dt><dd>{latest.checkpoint_state?.unresolved_competitor_ids?.length || 0}</dd></div>
          </dl>
          {latest.partial_completion ? <p className="warning">Partial results are preserved; unresolved competitors remain visible.</p> : null}
          <div className="discovery-inline-actions">
            {latest.state === "candidate" ? (
              <>
                <button type="button" onClick={() => onResearchAction(latest.id, "approve", latest)}>Approve research</button>
                <button type="button" className="secondary-button" onClick={() => onResearchAction(latest.id, "reject", latest)}>Reject</button>
              </>
            ) : null}
            {latest.state === "approved" && discovery?.current_candidate ? (
              <button type="button" onClick={() => onAttachResearch(discovery.current_candidate, latest)}>Attach to discovery candidate</button>
            ) : null}
            <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "refresh", { stale_only: false })}>Refresh all</button>
            <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "refresh", { stale_only: true })}>Refresh stale only</button>
          </div>
          <ItemList title="competitor profiles" items={latest.profiles} renderMeta={(item) => (
            <div className="discovery-evidence-meta">
              <span>{item.research_status}</span>
              <span>{item.evidence_quality || "Evidence quality not rated"}</span>
              <span>{Math.round((item.confidence || 0) * 100)}% confidence</span>
            </div>
          )} renderActions={(item) => latest.state === "candidate" ? (
            <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "remove_competitor", { competitor_id: item.id })}>Exclude from refresh</button>
          ) : null} />
          <ItemList title="inferred competitor pillars" items={latest.inferred_pillars} renderMeta={(item) => (
            <div className="discovery-evidence-meta">
              <span>{item.inference_strength?.replaceAll("_", " ")}</span>
              <span>{Math.round((item.confidence || 0) * 100)}% confidence</span>
              <span>{item.evidence_ids?.length || 0} evidence links</span>
            </div>
          )} renderActions={(item) => latest.state === "candidate" ? (
            <>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "required" })}>Require</button>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "optional" })}>Optional</button>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "excluded" })}>Exclude</button>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "stale" })}>Mark stale</button>
            </>
          ) : null} />
          <ItemList title="competitive territories" items={latest.territories} renderMeta={(item) => (
            <div className="discovery-evidence-meta"><span>{item.classification?.replaceAll("_", " ")}</span><span>Advisory only</span><span>{item.evidence_ids?.length || 0} evidence links</span></div>
          )} renderActions={(item) => latest.state === "candidate" ? (
            <>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "required" })}>Require</button>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "excluded" })}>Exclude</button>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "stale" })}>Mark stale</button>
            </>
          ) : null} />
          <ItemList title="competitive gaps" items={latest.gaps} renderMeta={(item) => (
            <div className="discovery-evidence-meta"><span>{item.gap_type?.replaceAll("_", " ")}</span><span>{Math.round((item.confidence || 0) * 100)}% confidence</span></div>
          )} renderActions={(item) => latest.state === "candidate" ? (
            <>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "optional" })}>Optional</button>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "excluded" })}>Exclude</button>
              <button type="button" className="secondary-button" onClick={() => onResearchEdit(latest, "finding", { finding_id: item.id, context_state: "stale" })}>Mark stale</button>
            </>
          ) : null} />
          {latest.evidence?.length ? (
            <div className="discovery-item-list">
              {latest.evidence.map((item) => (
                <article className="discovery-item-card" key={item.id}>
                  <div className="discovery-item-head"><div><span className="discovery-source competitor_research">{item.claim_type?.replaceAll("_", " ")}</span><h4>{item.source_title}</h4></div><span className="status-pill">{item.source_quality}</span></div>
                  <p>{item.claim_supported}</p>
                  <div className="discovery-evidence-meta"><span>{item.first_party ? "First-party" : "Third-party"}</span><span>{formatDate(item.retrieval_date)}</span><a href={item.source_location} target="_blank" rel="noreferrer">Inspect source</a></div>
                </article>
              ))}
            </div>
          ) : null}
          {latest.state === "candidate" ? (
            <div className="competitor-scope-form">
              <label>
                <span>Add competitor for a later refresh</span>
                <input value={competitorToAdd} onChange={(event) => setCompetitorToAdd(event.target.value)} />
              </label>
              <button type="button" disabled={!competitorToAdd.trim()} onClick={() => {
                onResearchEdit(latest, "add_competitor", { competitor_name: competitorToAdd.trim() });
                setCompetitorToAdd("");
              }}>Add competitor</button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export default function ProductDiscoveryPanel({
  brief,
  discovery,
  generationJobState,
  researchJobState,
  onGenerate,
  onRevisionAction,
  onDiscoveryEdit,
  onStartResearch,
  onResearchAction,
  onResearchEdit,
  onAttachResearch,
  onCancelJob,
}) {
  const [section, setSection] = useState("overview");
  const [mode, setMode] = useState("no_competitor_research");
  const [annotation, setAnnotation] = useState("");
  const [lensTitle, setLensTitle] = useState("");
  const [lensDescription, setLensDescription] = useState("");
  const publishedBrief = brief?.status === "published";
  const revision = discovery?.current_candidate || discovery?.published || discovery?.revisions?.at(-1);
  const generationRunning = ["queued", "running"].includes(generationJobState?.state);
  const reviewCounts = useMemo(() => {
    const findings = revision?.review_findings || [];
    return findings.reduce((result, item) => ({
      ...result,
      [item.outcome]: (result[item.outcome] || 0) + 1,
    }), {});
  }, [revision]);
  const revisionComparison = useMemo(() => {
    const revisions = discovery?.revisions || [];
    if (revisions.length < 2) return null;
    const left = revisions.at(-2)?.discovery || {};
    const right = revisions.at(-1)?.discovery || {};
    return Object.fromEntries(
      Object.keys(right).filter((key) => Array.isArray(right[key])).map((key) => {
        const leftIds = new Set((left[key] || []).map((item) => item.id));
        const rightIds = new Set((right[key] || []).map((item) => item.id));
        return [key, {
          added: [...rightIds].filter((id) => !leftIds.has(id)).length,
          removed: [...leftIds].filter((id) => !rightIds.has(id)).length,
        }];
      }),
    );
  }, [discovery?.revisions]);

  if (!publishedBrief) {
    return (
      <div className="discovery-locked-state">
        <span className="workspace-eyebrow">Product Discovery</span>
        <h3>Publish the Product Brief first</h3>
        <p>Discovery is linked to an exact published brief revision. Publishing does not start discovery automatically.</p>
      </div>
    );
  }

  if (!revision) {
    return (
      <div className="discovery-empty-state">
        <span className="workspace-eyebrow">Published brief ready</span>
        <h3>Examine the product before generating pillars</h3>
        <p>Generate reusable lenses, actors, lifecycle stages, overlapping domains, enterprise obligations, opportunities, risks, and open questions.</p>
        <label className="compact-select discovery-mode-select">
          <span>Competitor research mode</span>
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="no_competitor_research">No competitor research</option>
            <option value="lightweight_competitor_scan">Lightweight competitor scan</option>
            <option value="deep_competitor_research">Deep competitor research</option>
          </select>
        </label>
        <button type="button" onClick={() => onGenerate({ competitor_research_mode: mode })} disabled={generationRunning}>
          {generationRunning ? "Generating discovery" : "Generate Product Discovery"}
        </button>
        <p className="muted">Selecting a research mode records intent only. Research starts separately in its own section.</p>
        <WorkspaceJobNotice jobState={generationJobState} label="Product Discovery" onCancel={onCancelJob} />
      </div>
    );
  }

  const rawSections = revision.discovery || {};
  const itemStates = revision.human_owned_fields?.item_states || {};
  const sections = {
    ...rawSections,
    lenses: [
      ...(rawSections.lenses || []),
      ...(revision.human_owned_fields?.added_lenses || []),
    ].map((item) => ({
      ...item,
      downstream_state: itemStates[item.id] || item.downstream_state,
    })),
  };
  return (
    <div className="product-discovery-workspace">
      <nav className="discovery-subnav" aria-label="Product Discovery sections">
        {SECTIONS.map(([id, label]) => (
          <button type="button" className={section === id ? "active" : ""} onClick={() => setSection(id)} key={id}>{label}</button>
        ))}
      </nav>
      <div className="discovery-main">
        <header className="discovery-revision-header">
          <div>
            <span className="workspace-eyebrow">Source brief revision {revision.source_brief_revision_id?.slice(0, 8)}</span>
            <h3>Product Discovery revision {revision.revision_number}</h3>
            <p className="muted">Generated {formatDate(revision.created_at)} · {revision.competitor_research_mode?.replaceAll("_", " ")}</p>
          </div>
          <div className="discovery-revision-status">
            <span className={`status-pill ${revision.state}`}>{revision.state}</span>
            <span className={`status-pill ${revision.freshness_state}`}>{revision.freshness_state}</span>
          </div>
        </header>
        {revision.stale_reason ? <div className="brief-editor-notice warning"><strong>Discovery is stale</strong><span>{revision.stale_reason}</span></div> : null}
        <div className="discovery-inline-actions">
          {revision.state === "candidate" ? (
            <>
              <button type="button" onClick={() => onRevisionAction(revision.id, "approve", revision)}>Approve revision</button>
              <button type="button" className="secondary-button" onClick={() => onRevisionAction(revision.id, "reject", revision)}>Reject</button>
            </>
          ) : null}
          {revision.state === "approved" ? <button type="button" onClick={() => onRevisionAction(revision.id, "publish", revision)}>Publish discovery</button> : null}
          <button type="button" className="secondary-button" onClick={() => onGenerate({
            competitor_research_mode: revision.competitor_research_mode,
            competitor_research_revision_id: revision.competitor_research_revision_id,
          })} disabled={generationRunning}>
            Regenerate candidate
          </button>
          {revision.state === "candidate" && revision.competitor_research_revision_id ? (
            <button type="button" className="secondary-button" onClick={() => onDiscoveryEdit(revision, "detach_research")}>Detach competitor research</button>
          ) : null}
        </div>
        <WorkspaceJobNotice jobState={generationJobState} label="Product Discovery" onCancel={onCancelJob} />

        {section === "overview" ? (
          <section className="discovery-content-section">
            <div className="discovery-section-head">
              <div>
                <span className="workspace-eyebrow">Discovery overview</span>
                <h3>Product landscape</h3>
              </div>
            </div>
            <dl className="discovery-metrics">
              <div><dt>Lenses</dt><dd>{sections.lenses?.length || 0}</dd></div>
              <div><dt>Actors</dt><dd>{sections.actors?.length || 0}</dd></div>
              <div><dt>Domains</dt><dd>{sections.domains?.length || 0}</dd></div>
              <div><dt>Coverage risks</dt><dd>{sections.coverage_risks?.length || 0}</dd></div>
            </dl>
            <div className="discovery-review-summary">
              <strong>Practicality review</strong>
              <span>{reviewCounts.accepted || 0} accepted</span>
              <span>{reviewCounts.needs_human_review || 0} need human review</span>
              <span>{(reviewCounts.rejected_as_superficial || 0) + (reviewCounts.rejected_as_unsupported || 0)} flagged</span>
            </div>
            {revision.review_findings?.length ? (
              <div className="discovery-item-list">
                {revision.review_findings.map((item) => (
                  <article className="discovery-item-card" key={item.id}>
                    <div className="discovery-item-head">
                      <div><span className="discovery-source model_discovered">{item.reviewer_type} review</span><h4>{item.item_type.replaceAll("_", " ")}</h4></div>
                      <span className={`status-pill ${item.outcome}`}>{item.outcome.replaceAll("_", " ")}</span>
                    </div>
                    <p>{item.rationale}</p>
                    <div className="discovery-evidence-meta"><span>{Math.round((item.confidence || 0) * 100)}% confidence</span><span>{item.human_review_required ? "Human review required" : "Advisory"}</span></div>
                  </article>
                ))}
              </div>
            ) : null}
            {revision.human_owned_fields?.annotation ? (
              <div className="brief-editor-notice"><strong>Product-owner annotation</strong><span>{revision.human_owned_fields.annotation}</span></div>
            ) : null}
            <ItemList title="product archetypes" items={sections.archetypes} renderMeta={(item) => (
              <div className="discovery-evidence-meta"><span>{Math.round((item.confidence || 0) * 100)}% confidence</span><span>{item.rationale}</span></div>
            )} />
            <div className="competitor-scope-form">
              <label>
                <span>Human annotation</span>
                <textarea value={annotation} onChange={(event) => setAnnotation(event.target.value)} placeholder="Record a product-owner decision or review note." />
              </label>
              <button type="button" disabled={!annotation.trim()} onClick={() => {
                onDiscoveryEdit(revision, "human_fields", { updates: { annotation: annotation.trim() } });
                setAnnotation("");
              }}>Save annotation as new revision</button>
            </div>
          </section>
        ) : null}
        {section === "lenses" ? (
          <section className="discovery-content-section">
            <ItemList
              title="lenses"
              items={sections.lenses}
              renderMeta={(item) => <div className="discovery-evidence-meta"><span>{item.recommendation}</span><span>{item.questions?.length || 0} questions</span><span>{item.omission_risks?.length || 0} omission risks</span></div>}
              renderActions={(item) => revision.state === "candidate" ? (
                <button type="button" className="secondary-button" onClick={() => onDiscoveryEdit(revision, "exclude_lens", { lens_id: item.id, excluded: item.downstream_state !== "excluded" })}>
                  {item.downstream_state === "excluded" ? "Restore lens" : "Exclude from Layer 1 context"}
                </button>
              ) : null}
            />
            {revision.state === "candidate" ? (
              <div className="competitor-scope-form">
                <label><span>Human-authored lens</span><input value={lensTitle} onChange={(event) => setLensTitle(event.target.value)} placeholder="Lens title" /></label>
                <label><span>Description</span><textarea value={lensDescription} onChange={(event) => setLensDescription(event.target.value)} /></label>
                <button type="button" disabled={!lensTitle.trim() || !lensDescription.trim()} onClick={() => {
                  onDiscoveryEdit(revision, "add_lens", {
                    lens: {
                      id: crypto.randomUUID(),
                      title: lensTitle.trim(),
                      description: lensDescription.trim(),
                      questions: [],
                      omission_risks: [],
                      rationale: "Added by the product owner.",
                      confidence: 1,
                      recommendation: "include",
                    },
                  });
                  setLensTitle("");
                  setLensDescription("");
                }}>Add lens as new revision</button>
              </div>
            ) : null}
          </section>
        ) : null}
        {section === "actors" ? <ItemList title="actors" items={sections.actors} renderMeta={(item) => <div className="discovery-evidence-meta"><span>{item.authority_level || "Authority not specified"}</span><span>{item.workflows?.length || 0} workflows</span></div>} /> : null}
        {section === "lifecycle_stages" ? <ItemList title="lifecycle stages" items={sections.lifecycle_stages} renderMeta={(item) => <div className="discovery-evidence-meta"><span>{item.actor_ids?.length || 0} actors</span><span>{item.failure_modes?.length || 0} failure modes</span></div>} /> : null}
        {section === "domains" ? <ItemList title="product domains" items={sections.domains} renderMeta={(item) => <div className="discovery-evidence-meta"><span>{Math.round((item.confidence || 0) * 100)}% confidence</span><span>Overlap is allowed at discovery stage</span></div>} /> : null}
        {section === "enterprise_obligations" ? <ItemList title="enterprise obligations" items={sections.enterprise_obligations} renderMeta={(item) => <div className="discovery-evidence-meta"><span>{item.strategic_classification?.replaceAll("_", " ")}</span><span>{item.likely_product_destination}</span></div>} /> : null}
        {section === "cross_domain_opportunities" ? <ItemList title="cross-domain opportunities" items={sections.cross_domain_opportunities} renderMeta={(item) => <div className="discovery-evidence-meta"><span>{item.source_domain}</span><span>{item.speculation_level?.replaceAll("_", " ")}</span></div>} /> : null}
        {section === "coverage_risks" ? <ItemList title="coverage risks" items={sections.coverage_risks} renderMeta={(item) => <div className="discovery-evidence-meta"><span>{item.severity} severity</span><span>{item.human_review_required ? "Human review required" : "Advisory"}</span></div>} /> : null}
        {section === "open_questions" ? <ItemList title="open questions" items={sections.open_questions} renderMeta={(item) => <div className="discovery-evidence-meta"><span>{item.disposition?.replaceAll("_", " ")}</span><span>{item.why_it_matters}</span></div>} /> : null}
        {section === "competitor_research" ? (
          <CompetitorResearchSection
            discovery={discovery}
            researchJobState={researchJobState}
            onStartResearch={onStartResearch}
            onResearchAction={onResearchAction}
            onResearchEdit={onResearchEdit}
            onAttachResearch={onAttachResearch}
            onCancelJob={onCancelJob}
          />
        ) : null}
        {section === "revision_history" ? (
          <section className="discovery-content-section">
            <div className="discovery-section-head"><div><span className="workspace-eyebrow">Immutable history</span><h3>Revision history</h3></div></div>
            <div className="discovery-revision-list">
              {[...(discovery?.revisions || [])].reverse().map((item) => (
                <article key={item.id}>
                  <div><strong>Revision {item.revision_number}</strong><span>{formatDate(item.created_at)}</span></div>
                  <div>
                    <span className={`status-pill ${item.state}`}>{item.state}</span>
                    <span className={`status-pill ${item.freshness_state}`}>{item.freshness_state}</span>
                    {item.id !== revision.id ? <button type="button" className="secondary-button" onClick={() => onRevisionAction(item.id, "restore", item)}>Restore as candidate</button> : null}
                  </div>
                </article>
              ))}
            </div>
            {revisionComparison ? (
              <div className="discovery-review-summary">
                <strong>Latest revision comparison</strong>
                {Object.entries(revisionComparison).map(([name, counts]) => (
                  <span key={name}>{name.replaceAll("_", " ")}: +{counts.added} / -{counts.removed}</span>
                ))}
              </div>
            ) : <p className="muted">Generate or edit another revision to compare stable item IDs.</p>}
          </section>
        ) : null}
      </div>
    </div>
  );
}
