import { useEffect, useRef, useState } from "react";
import TreeDashboard from "./treeDashboard";

const API_BASE = "http://127.0.0.1:8000/api";
const TABS = ["Layer 0", "Generate", "Review", "Tree", "Specs", "Settings", "Export"];
const LLM_ASSIGNMENT_LABELS = {
  layer0_plan: "Layer 0 Plan Chat",
  layer0_extraction: "Layer 0 Brief Extraction",
  layer1_generation: "Layer 1 Generation",
  layer2_generation: "Layer 2 Generation",
  layer3_generation: "Layer 3 Spec Generation",
  layer0_research: "Layer 0 Research Discovery",
  layer1_research: "Layer 1 Research Discovery",
};
const EMBEDDING_ASSIGNMENT_LABELS = {
  layer1_similarity_embeddings: "Layer 1 Similarity",
  research_embeddings: "Research Embeddings",
};
const ASSIGNMENT_HELP = {
  layer0_plan: "Use this model for the live Layer 0 intake conversation and brief shaping.",
  layer0_extraction: "Use this model to turn Plan mode messages into structured brief fields.",
  layer1_generation: "Use one or more models to brainstorm and broaden the Layer 1 pillar set.",
  layer2_generation: "Use this model to expand selected pillars into Layer 2 subfeatures.",
  layer3_generation: "Use this model to draft the final Layer 3 spec cards.",
  layer0_research: "Use this model to discover and summarize competitor evidence for Layer 0.",
  layer1_research: "Use this model to score how each Layer 1 pillar shows up across competitors.",
  layer1_similarity_embeddings: "Use this embedding model to measure overlap between Layer 1 pillars.",
  research_embeddings: "Use this embedding model to index research pages and compare evidence chunks.",
};
const ASSIGNMENT_GROUPS = [
  {
    title: "Layer 0",
    fields: ["layer0_plan", "layer0_extraction", "layer0_research"],
  },
  {
    title: "Generation",
    fields: ["layer1_generation", "layer2_generation", "layer3_generation"],
  },
  {
    title: "Embeddings",
    fields: ["layer1_similarity_embeddings", "research_embeddings", "layer1_research"],
  },
];
const GUIDE_SECTIONS = [
  {
    title: "How SpecForge flows",
    body: "Create a project, shape the Layer 0 brief in Plan or Form mode, publish it, then expand into Layers 1 through 3 with research and review along the way.",
  },
  {
    title: "What app defaults do",
    body: "App Settings define the reusable model profiles and default assignments that seed new projects. Existing projects keep their own overrides unless you edit them directly.",
  },
  {
    title: "What project overrides do",
    body: "Each project can override the global defaults for planning, generation, research, and embeddings without changing the rest of the library.",
  },
];
const PROMPT_FIELD_HELP = {
  system_json_generator: "Base system instruction for every structured JSON response.",
  layer0_brief_extraction: "Extracts brief field updates from Plan mode messages.",
  layer0_plan_guidance: "Shapes the short assistant reply and next questions in Plan mode.",
  layer1_pillar_generation: "Guides broad Layer 1 pillar brainstorming.",
  layer1_pillar_normalization: "Cleans raw Layer 1 ideas into stable pillar concepts.",
  layer1_pillar_assessment: "Scores and clusters candidate Layer 1 pillars.",
  layer1_pillar_research_assessment: "Rates how hard a pillar looks to build, run, and maintain after competitor research.",
  layer2_subfeature_generation: "Expands a pillar into Layer 2 subfeatures.",
  layer3_spec_generation: "Drafts the final Layer 3 implementation spec.",
  coverage_critic: "Summarizes overlap and saturation across generation loops.",
  json_schema_repair: "Repairs near-miss model output into valid JSON.",
};

// Fetch JSON from the local API and surface readable errors to the UI.
async function apiFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

// Create a simple display label for the project selector.
function projectLabel(project) {
  return `${project.name} | ${new Date(project.created_at).toLocaleString()}`;
}

function formatProjectCardDate(value) {
  return new Date(value).toLocaleString();
}

function sortProjects(projects, sortOrder) {
  const copy = [...projects];
  copy.sort((left, right) => {
    const leftTime = new Date(left.created_at).getTime();
    const rightTime = new Date(right.created_at).getTime();
    return sortOrder === "oldest" ? leftTime - rightTime : rightTime - leftTime;
  });
  return copy;
}

// Keep only the items a human has approved for downward expansion.
function approvedNodes(nodes, nodeType) {
  return nodes.filter((node) => node.node_type === nodeType && ["kept", "prioritized"].includes(node.status));
}

// Build a label-to-id map for checkbox lists and selectors.
function choiceMap(nodes) {
  return Object.fromEntries(nodes.map((node) => [`${node.title} (${node.status})`, node.id]));
}

function textToList(value) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToText(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

function briefProgressItems(brief) {
  return [
    {
      label: "Product Idea",
      ready: Boolean(brief?.product_idea?.trim()),
      summary: brief?.product_idea?.trim() || "Still open",
    },
    {
      label: "Target Users",
      ready: Boolean(brief?.target_users?.trim()),
      summary: brief?.target_users?.trim() || "Still open",
    },
    {
      label: "Constraints",
      ready: Boolean(brief?.constraints?.trim()),
      summary: brief?.constraints?.trim() || "Still open",
    },
    {
      label: "Goals",
      ready: Boolean(brief?.goals?.length),
      summary: brief?.goals?.slice(0, 2).join(", ") || "Still open",
    },
    {
      label: "Competitors",
      ready: Boolean(brief?.known_competitors?.length),
      summary: brief?.known_competitors?.slice(0, 2).join(", ") || "Still open",
    },
  ];
}

function planSuggestionsFromBrief(brief) {
  if (!brief?.product_idea?.trim()) {
    return [
      "Help me frame the product idea before we lock the brief.",
      "Ask me the questions you need to understand the product direction.",
      "Help me shape the first version of this idea for a real target user.",
    ];
  }
  if (!brief?.target_users?.trim()) {
    return [
      "Help me narrow the target users for this product.",
      "Ask me questions that separate primary users from edge users.",
      "Pressure test who this is really for and who it is not for.",
    ];
  }
  if (!brief?.known_competitors?.length) {
    return [
      "Help me brainstorm likely competitors or substitutes.",
      "What products should we compare against before publishing?",
      "Ask me enough questions to map the competitor landscape.",
    ];
  }
  if (!brief?.constraints?.trim()) {
    return [
      "Help me surface the constraints that should shape this project.",
      "What technical or business constraints should we capture now?",
      "Ask me about the tradeoffs that should go into the brief.",
    ];
  }
  return [
    "Challenge the brief and tell me what still feels fuzzy.",
    "Ask me the next two questions you need before we publish.",
    "Help me sharpen goals, risks, and the most promising direction.",
  ];
}

function extractedUpdateBadges(turn) {
  if (!turn?.extracted_updates || typeof turn.extracted_updates !== "object") {
    return [];
  }
  const briefUpdates = turn.extracted_updates.brief_updates;
  if (briefUpdates && typeof briefUpdates === "object") {
    return Object.keys(briefUpdates).filter(Boolean);
  }
  return Object.keys(turn.extracted_updates).filter(Boolean);
}

function latestPlanGuidance(conversation) {
  const reversed = [...conversation].reverse();
  for (const turn of reversed) {
    const guidance = turn?.extracted_updates?.plan_guidance;
    if (guidance && typeof guidance === "object") {
      return guidance;
    }
  }
  return null;
}

// Render a checkbox group for multi-select generation actions.
function CheckboxList({ title, options, selectedValues, onChange }) {
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
function NodeEditor({ node, onSave, findings, onRerunResearch }) {
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
function GenerationSummary({ summary }) {
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

function ResearchStatus({ jobs, onRerunLayer0, onRerunLayer1 }) {
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

function MarketPanel({ findings }) {
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

function BriefWorkspace({ brief, conversation, onSave, onChat, onPublish }) {
  const [mode, setMode] = useState("Plan");
  const [form, setForm] = useState(brief);
  const [message, setMessage] = useState("");
  const [planState, setPlanState] = useState("idle");
  const [snapshotOpen, setSnapshotOpen] = useState(true);
  const chatLogRef = useRef(null);

  useEffect(() => {
    setForm(brief);
  }, [brief]);

  useEffect(() => {
    if (!chatLogRef.current) {
      return;
    }
    chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
  }, [conversation.length, planState]);

  function updateField(field, value) {
    setForm({ ...form, [field]: value });
  }

  const payload = {
    product_idea: form.product_idea || "",
    known_competitors: Array.isArray(form.known_competitors) ? form.known_competitors : textToList(form.known_competitors || ""),
    constraints: form.constraints || "",
    target_users: form.target_users || "",
    goals: Array.isArray(form.goals) ? form.goals : textToList(form.goals || ""),
    preferred_directions: Array.isArray(form.preferred_directions) ? form.preferred_directions : textToList(form.preferred_directions || ""),
    rejected_directions: Array.isArray(form.rejected_directions) ? form.rejected_directions : textToList(form.rejected_directions || ""),
    notes: form.notes || "",
  };
  const progressItems = briefProgressItems(payload);
  const guidance = latestPlanGuidance(conversation);
  const suggestions = guidance?.next_questions?.length ? guidance.next_questions : planSuggestionsFromBrief(payload);

  async function sendPlanMessage(nextMessage) {
    const clean = nextMessage.trim();
    if (!clean) {
      return;
    }
    setPlanState("sending");
    try {
      await onChat(clean);
      setMessage("");
      setPlanState("idle");
    } catch {
      setPlanState("error");
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h3>Layer 0 Brief</h3>
          <span className={`status-pill ${brief.status}`}>{brief.status}</span>
        </div>
        <div className="segmented">
          {["Plan", "Form"].map((item) => (
            <button key={item} type="button" className={mode === item ? "active" : ""} onClick={() => setMode(item)}>
              {item}
            </button>
          ))}
        </div>
      </div>

      {mode === "Plan" ? (
        <div className="plan-workspace">
          <div className="plan-chat-panel">
            <div className="plan-mode-header">
              <div>
                <h4>Plan Conversation</h4>
                <p className="muted">
                  Use this like a working session with an intake agent. The assistant should help discover the brief,
                  ask follow-up questions, and keep the draft moving toward publish.
                </p>
              </div>
              <div className="plan-chip-row">
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="preset-chip"
                    onClick={() => {
                      setMessage(suggestion);
                    }}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>

            <div ref={chatLogRef} className="chat-log plan-chat-log">
              {!conversation.length ? (
                <div className="chat-turn assistant starter">
                  <strong>SpecForge</strong>
                  <p>
                    I can help shape the draft brief before anything gets published. Start with the product idea,
                    the user problem, or just the rough direction, and I&apos;ll pull structure out as we go.
                  </p>
                  <p className="muted">A good first turn is usually the product idea, target user, or what feels most uncertain.</p>
                </div>
              ) : null}
              {conversation.map((turn) => {
                const updates = extractedUpdateBadges(turn);
                return (
                  <div key={turn.id} className={`chat-turn ${turn.role}`}>
                    <div className="chat-turn-head">
                      <strong>{turn.role === "assistant" ? "SpecForge" : "You"}</strong>
                      {updates.length ? <span className="chat-turn-meta">Updated: {updates.join(", ")}</span> : null}
                    </div>
                    <p>{turn.content}</p>
                  </div>
                );
              })}
              {planState === "sending" ? (
                <div className="chat-turn assistant loading">
                  <strong>SpecForge</strong>
                  <p>Updating the draft brief and preparing the next question.</p>
                </div>
              ) : null}
            </div>

            <form
              className="plan-composer"
              onSubmit={(event) => {
                event.preventDefault();
                sendPlanMessage(message);
              }}
            >
              <label>
                Message
                <textarea
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  rows={5}
                  placeholder="Describe the product, answer the assistant, or ask it to challenge the brief."
                />
              </label>
              <div className="panel-header">
                <p className="muted plan-composer-note">The draft brief updates continuously, but Layer 1 stays locked until you publish.</p>
                <button type="submit" disabled={planState === "sending" || !message.trim()}>
                  {planState === "sending" ? "Thinking..." : "Send"}
                </button>
              </div>
            </form>
          </div>

          <aside className={snapshotOpen ? "plan-brief-sidebar" : "plan-brief-sidebar collapsed"}>
            {!snapshotOpen ? (
              <button type="button" className="snapshot-reopen-tab" onClick={() => setSnapshotOpen(true)}>
                Open Brief Snapshot
              </button>
            ) : null}
            {guidance ? (
              <div className="plan-sidebar-section">
                <div className="panel-header">
                  <h4>Agent Focus</h4>
                  <span className="status-pill">{guidance.confidence}</span>
                </div>
                <p className="muted">{guidance.recap}</p>
                <div className="plan-focus-card">
                  <span>Current focus</span>
                  <strong>{guidance.focus_area.replaceAll("_", " ")}</strong>
                </div>
                {guidance.next_questions?.length ? (
                  <ul className="summary-list">
                    {guidance.next_questions.map((question) => (
                      <li key={question}>{question}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}

            {snapshotOpen ? (
              <>
                <div className="plan-sidebar-section">
                  <div className="panel-header">
                    <h4>Draft Brief Snapshot</h4>
                    <div className="button-row">
                      <button type="button" className="secondary-button" onClick={() => setMode("Form")}>Open Form</button>
                      <button type="button" className="secondary-button" onClick={() => setSnapshotOpen(false)}>Hide</button>
                    </div>
                  </div>
                  <div className="plan-progress-grid">
                    {progressItems.map((item) => (
                      <div key={item.label} className={`plan-progress-card ${item.ready ? "ready" : "open"}`}>
                        <span>{item.label}</span>
                        <strong>{item.ready ? "Captured" : "Open"}</strong>
                        <p>{item.summary}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="plan-sidebar-section">
                  <h4>What To Cover Next</h4>
                  <ul className="summary-list">
                    {progressItems.filter((item) => !item.ready).length ? (
                      progressItems.filter((item) => !item.ready).map((item) => (
                        <li key={item.label}>{item.label}</li>
                      ))
                    ) : (
                      <li>The main brief fields are populated. Use Plan mode to pressure test the direction before publishing.</li>
                    )}
                  </ul>
                </div>
              </>
            ) : (
              <div className="plan-sidebar-collapsed-spacer" aria-hidden="true" />
            )}
          </aside>
        </div>
      ) : null}

      {mode === "Form" ? (
        <div className="brief-grid">
          <label>
            Product Idea
            <textarea value={payload.product_idea} onChange={(event) => updateField("product_idea", event.target.value)} rows={4} />
          </label>
          <label>
            Known Competitors
            <textarea value={listToText(payload.known_competitors)} onChange={(event) => updateField("known_competitors", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Target Users
            <textarea value={payload.target_users} onChange={(event) => updateField("target_users", event.target.value)} rows={3} />
          </label>
          <label>
            Constraints
            <textarea value={payload.constraints} onChange={(event) => updateField("constraints", event.target.value)} rows={3} />
          </label>
          <label>
            Goals
            <textarea value={listToText(payload.goals)} onChange={(event) => updateField("goals", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Preferred Directions
            <textarea value={listToText(payload.preferred_directions)} onChange={(event) => updateField("preferred_directions", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Rejected Directions
            <textarea value={listToText(payload.rejected_directions)} onChange={(event) => updateField("rejected_directions", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Notes
            <textarea value={payload.notes} onChange={(event) => updateField("notes", event.target.value)} rows={4} />
          </label>
          <button type="button" onClick={() => onSave(payload)}>Save Brief</button>
        </div>
      ) : null}

      <div className="publish-row">
        <button type="button" onClick={onPublish}>Publish to Layer 1</button>
      </div>
    </div>
  );
}

function ProjectHub({
  projects,
  sortOrder,
  onSortOrderChange,
  onOpenProject,
  onCreateProject,
}) {
  return (
    <section className="project-hub">
      <div className="hub-header">
        <div>
          <h1>Project Library</h1>
          <p className="muted">Open a project to keep building, or create a new one and jump straight into Layer 0.</p>
        </div>
        <div className="hub-actions">
          <button type="button" onClick={onCreateProject}>Create New Project</button>
          <label className="compact-select">
            Sort
            <select value={sortOrder} onChange={(event) => onSortOrderChange(event.target.value)}>
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
            </select>
          </label>
        </div>
      </div>
      {projects.length ? (
        <div className="project-grid">
          {projects.map((project) => (
            <button key={project.id} type="button" className="project-card" onClick={() => onOpenProject(project.id)}>
              <div className="project-card-head">
                <strong>{project.name}</strong>
                <span className={`status-pill ${project.brief_status || "draft"}`}>{project.brief_status || "draft"}</span>
              </div>
              <p>{project.idea}</p>
              <div className="project-card-meta">
                <span>Created {formatProjectCardDate(project.created_at)}</span>
                <span>{project.node_count || 0} nodes</span>
                <span>{project.pillar_count || 0} pillars</span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="panel">
          <p className="muted">No projects yet. Use the Create New Project button to start the first brief.</p>
        </div>
      )}
    </section>
  );
}

function ModalFrame({ title, subtitle, onClose, children, className = "" }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div className={`modal-shell ${className}`.trim()} role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p className="muted">{subtitle}</p> : null}
          </div>
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function CreateProjectModal({ name, idea, onNameChange, onIdeaChange, onSubmit, onClose }) {
  return (
    <ModalFrame
      title="Create New Project"
      subtitle="Name the project, capture the product idea, and jump right into Layer 0."
      onClose={onClose}
      className="compact-modal"
    >
      <form className="modal-form" onSubmit={onSubmit}>
        <label>
          Name
          <input value={name} onChange={(event) => onNameChange(event.target.value)} autoFocus />
        </label>
        <label>
          Product Idea
          <textarea value={idea} onChange={(event) => onIdeaChange(event.target.value)} rows={6} />
        </label>
        <div className="modal-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" disabled={!name.trim() || !idea.trim()}>Create Project</button>
        </div>
      </form>
    </ModalFrame>
  );
}

function GuideModal({ onClose }) {
  return (
    <ModalFrame
      title="Guide"
      subtitle="A quick explanation of how the app fits together."
      onClose={onClose}
      className="compact-modal"
    >
      <div className="guide-stack">
        {GUIDE_SECTIONS.map((section) => (
          <div key={section.title} className="guide-card">
            <strong>{section.title}</strong>
            <p className="muted">{section.body}</p>
          </div>
        ))}
      </div>
    </ModalFrame>
  );
}

function PromptCatalogEditor({ settings, onChange, onSave, saveState }) {
  if (!settings) {
    return (
      <div className="panel">
        <p className="muted">Prompts are loading.</p>
      </div>
    );
  }

  const promptCatalog = settings.prompt_catalog || {};
  const promptEntries = Object.entries(promptCatalog);

  function updatePrompt(key, value) {
    onChange({
      ...settings,
      prompt_catalog: {
        ...promptCatalog,
        [key]: value,
      },
    });
  }

  return (
    <div className="prompt-editor">
      <div className="panel prompt-editor-header">
        <div>
          <h3>System Prompt Catalog</h3>
          <p className="muted">
            Changes here only affect projects created after you save. Existing projects keep the prompt snapshot they already have.
          </p>
        </div>
        <button type="button" onClick={onSave} disabled={saveState === "saving"}>
          {saveState === "saving" ? "Saving..." : "Save Prompts"}
        </button>
      </div>

      <div className="prompt-grid">
        {promptEntries.map(([key, value]) => (
          <div key={key} className="panel prompt-card">
            <div className="prompt-card-header">
              <div>
                <h4>{key}</h4>
                <p className="muted">{PROMPT_FIELD_HELP[key] || "Editable template used by the local generation pipeline."}</p>
              </div>
            </div>
            <textarea
              className="prompt-textarea"
              value={value}
              onChange={(event) => updatePrompt(key, event.target.value)}
              rows={10}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function AssignmentField({ label, help, children }) {
  return (
    <div className="assignment-field" title={help}>
      <div className="assignment-label-row">
        <strong>{label}</strong>
        <span className="tooltip-chip" aria-label={help} title={help}>?</span>
      </div>
      <p className="field-help">{help}</p>
      {children}
    </div>
  );
}

function ModelSettingsEditor({
  settings,
  config,
  saveState,
  onChange,
  onSave,
  title,
  description,
  saveLabel,
  showRuntimeFields = false,
}) {
  if (!settings) {
    return (
      <div className="panel">
        <p className="muted">Settings are loading.</p>
      </div>
    );
  }

  const llmProfiles = settings.llm_profiles || [];
  const embeddingProfiles = settings.embedding_profiles || [];
  const assignments = settings.assignments || {};

  function updateRootField(field, value) {
    onChange({ ...settings, [field]: value });
  }

  function updateLlmProfile(index, field, value) {
    const next = llmProfiles.map((profile, profileIndex) => (
      profileIndex === index ? { ...profile, [field]: value } : profile
    ));
    onChange({ ...settings, llm_profiles: next });
  }

  function updateEmbeddingProfile(index, field, value) {
    const next = embeddingProfiles.map((profile, profileIndex) => (
      profileIndex === index ? { ...profile, [field]: value } : profile
    ));
    onChange({ ...settings, embedding_profiles: next });
  }

  function updateAssignment(field, value) {
    onChange({ ...settings, assignments: { ...assignments, [field]: value } });
  }

  function addLlmProfile() {
    onChange({
      ...settings,
      llm_profiles: [
        ...llmProfiles,
        { id: `llm-${Date.now()}`, label: "New LLM", base_url: "", model_name: "", local_path: "" },
      ],
    });
  }

  function addEmbeddingProfile() {
    onChange({
      ...settings,
      embedding_profiles: [
        ...embeddingProfiles,
        { id: `embed-${Date.now()}`, label: "New Embeddings", model_name: "" },
      ],
    });
  }

  return (
    <div className="settings-editor">
      <div className="panel">
        <div className="panel-header">
          <h3>{title}</h3>
          <button type="button" onClick={onSave} disabled={saveState === "saving"}>
            {saveState === "saving" ? "Saving..." : saveLabel}
          </button>
        </div>
        <p className="muted">{description}</p>
      </div>

      {showRuntimeFields ? (
        <div className="panel">
          <h3>Runtime Defaults</h3>
          <div className="brief-grid">
            <label>
              Chat API Base URL
              <input
                value={settings.llama_base_url || ""}
                onChange={(event) => updateRootField("llama_base_url", event.target.value)}
                placeholder="http://127.0.0.1:8080"
              />
            </label>
            <label>
              Default Chat Model Name
              <input
                value={settings.llm_model_name || ""}
                onChange={(event) => updateRootField("llm_model_name", event.target.value)}
                placeholder="qwen-27b-q3-no-thinking"
              />
            </label>
            <label>
              Default Local GGUF Path
              <input
                value={settings.preferred_model_path || ""}
                onChange={(event) => updateRootField("preferred_model_path", event.target.value)}
                placeholder="C:\\models\\my-model.gguf"
              />
            </label>
            <label>
              Default Embedding Model
              <input
                value={settings.embeddings_model_name || ""}
                onChange={(event) => updateRootField("embeddings_model_name", event.target.value)}
                placeholder="sentence-transformers/all-MiniLM-L6-v2"
              />
            </label>
          </div>
          <div className="preset-grid">
            {(config.embedding_model_presets || []).map((preset) => (
              <button key={preset} type="button" className="preset-chip" onClick={() => updateRootField("embeddings_model_name", preset)}>
                {preset}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="panel">
        <div className="panel-header">
          <h3>LLM Profiles</h3>
          <button type="button" onClick={addLlmProfile}>Add LLM</button>
        </div>
        {llmProfiles.map((profile, index) => (
          <div key={profile.id || index} className="settings-block">
            <div className="panel-header">
              <strong>{profile.label || `LLM ${index + 1}`}</strong>
              <button type="button" className="secondary-button" onClick={() => onChange({ ...settings, llm_profiles: llmProfiles.filter((_, profileIndex) => profileIndex !== index) })}>
                Remove
              </button>
            </div>
            <div className="brief-grid">
              <label>
                Profile ID
                <input value={profile.id || ""} onChange={(event) => updateLlmProfile(index, "id", event.target.value)} />
              </label>
              <label>
                Label
                <input value={profile.label || ""} onChange={(event) => updateLlmProfile(index, "label", event.target.value)} />
              </label>
              <label>
                API Base URL
                <input value={profile.base_url || ""} onChange={(event) => updateLlmProfile(index, "base_url", event.target.value)} placeholder="http://127.0.0.1:8080" />
              </label>
              <label>
                Model Name
                <input value={profile.model_name || ""} onChange={(event) => updateLlmProfile(index, "model_name", event.target.value)} placeholder="qwen-27b-q3-no-thinking" />
              </label>
              <label>
                Local GGUF Path
                <input value={profile.local_path || ""} onChange={(event) => updateLlmProfile(index, "local_path", event.target.value)} placeholder="C:\\models\\my-model.gguf" />
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-header">
          <h3>Embedding Profiles</h3>
          <button type="button" onClick={addEmbeddingProfile}>Add Embeddings</button>
        </div>
        {embeddingProfiles.map((profile, index) => (
          <div key={profile.id || index} className="settings-block">
            <div className="panel-header">
              <strong>{profile.label || `Embeddings ${index + 1}`}</strong>
              <button type="button" className="secondary-button" onClick={() => onChange({ ...settings, embedding_profiles: embeddingProfiles.filter((_, profileIndex) => profileIndex !== index) })}>
                Remove
              </button>
            </div>
            <div className="brief-grid">
              <label>
                Profile ID
                <input value={profile.id || ""} onChange={(event) => updateEmbeddingProfile(index, "id", event.target.value)} />
              </label>
              <label>
                Label
                <input value={profile.label || ""} onChange={(event) => updateEmbeddingProfile(index, "label", event.target.value)} />
              </label>
              <label>
                Model ID or Local Path
                <input value={profile.model_name || ""} onChange={(event) => updateEmbeddingProfile(index, "model_name", event.target.value)} placeholder="sentence-transformers/all-MiniLM-L6-v2" />
              </label>
            </div>
            <div className="preset-grid">
              {(config.embedding_model_presets || []).map((preset) => (
                <button key={`${profile.id}-${preset}`} type="button" className="preset-chip" onClick={() => updateEmbeddingProfile(index, "model_name", preset)}>
                  {preset}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3>Assignments</h3>
        <div className="assignment-groups">
          {[
            { title: "Layer 0", fields: ["layer0_plan", "layer0_extraction", "layer0_research"] },
            { title: "Generation", fields: ["layer1_generation", "layer2_generation", "layer3_generation"] },
            { title: "Research And Embeddings", fields: ["layer1_research", "layer1_similarity_embeddings", "research_embeddings"] },
          ].map((group) => (
            <div key={group.title} className="assignment-group">
              <h4>{group.title}</h4>
              <div className="brief-grid">
                {group.fields.map((key) => {
                  const label = LLM_ASSIGNMENT_LABELS[key] || EMBEDDING_ASSIGNMENT_LABELS[key];
                  const isLayer1Generation = key === "layer1_generation";
                  const isEmbeddingField = key in EMBEDDING_ASSIGNMENT_LABELS;
                  const options = isEmbeddingField ? embeddingProfiles : llmProfiles;
                  return (
                    <AssignmentField key={key} label={label} help={ASSIGNMENT_HELP[key]}>
                      {isLayer1Generation ? (
                        <div className="checkbox-grid">
                          {llmProfiles.map((profile) => (
                            <label key={`${key}-${profile.id}`} className="checkbox-item">
                              <input
                                type="checkbox"
                                checked={(assignments[key] || []).includes(profile.id)}
                                onChange={(event) => {
                                  const current = Array.isArray(assignments[key]) ? assignments[key] : [];
                                  if (event.target.checked) {
                                    updateAssignment(key, [...current, profile.id]);
                                    return;
                                  }
                                  updateAssignment(key, current.filter((item) => item !== profile.id));
                                }}
                              />
                              <span>{profile.label}</span>
                            </label>
                          ))}
                        </div>
                      ) : (
                        <select value={assignments[key] || ""} onChange={(event) => updateAssignment(key, event.target.value)}>
                          {options.map((profile) => (
                            <option key={profile.id} value={profile.id}>{profile.label}</option>
                          ))}
                        </select>
                      )}
                    </AssignmentField>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AppSettingsModal({ settings, config, saveState, onChange, onSave, onClose }) {
  return (
    <ModalFrame
      title="Settings"
      subtitle="Manage reusable app defaults, model profiles, embeddings, and assignment routing for new projects."
      onClose={onClose}
      className="settings-modal"
    >
      <div className="tab-content">
        <ModelSettingsEditor
          settings={settings}
          config={config}
          saveState={saveState}
          onChange={onChange}
          onSave={onSave}
          title="App Defaults"
          description="These defaults seed new projects and act as the reusable baseline. Existing project overrides stay untouched unless you edit that project."
          saveLabel="Save App Settings"
          showRuntimeFields
        />
      </div>
    </ModalFrame>
  );
}

function ProjectSettingsTab({ settings, config, saveState, onChange, onSave }) {
  if (!settings) {
    return (
      <section className="tab-content">
        <div className="panel">
          <p className="muted">Project settings are loading.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="tab-content">
      <ModelSettingsEditor
        settings={settings}
        config={config}
        saveState={saveState}
        onChange={onChange}
        onSave={onSave}
        title="Project Model Overrides"
        description="These settings override the reusable app defaults only for this project."
        saveLabel="Save Project Overrides"
      />
    </section>
  );
}

// Keep the localhost UI focused on fast end-to-end project work.
export default function App() {
  const [config, setConfig] = useState(null);
  const [projects, setProjects] = useState([]);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [snapshot, setSnapshot] = useState(null);
  const [appSettings, setAppSettings] = useState(null);
  const [projectModelSettings, setProjectModelSettings] = useState(null);
  const [activeTab, setActiveTab] = useState("Layer 0");
  const [statusMessage, setStatusMessage] = useState("Loading SpecForge...");
  const [error, setError] = useState("");
  const [lastSummary, setLastSummary] = useState(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectIdea, setNewProjectIdea] = useState("");
  const [sortOrder, setSortOrder] = useState("newest");
  const [navOpen, setNavOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [showPrompts, setShowPrompts] = useState(false);
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [modelSettingsSaveState, setModelSettingsSaveState] = useState("idle");
  const [projectSettingsSaveState, setProjectSettingsSaveState] = useState("idle");
  const [layer1Thinking, setLayer1Thinking] = useState(false);
  const [layer1MaxRounds, setLayer1MaxRounds] = useState(6);
  const [layer1TargetPerRound, setLayer1TargetPerRound] = useState(12);
  const [layer1MinNew, setLayer1MinNew] = useState(2);
  const [layer2Selected, setLayer2Selected] = useState([]);
  const [layer2Thinking, setLayer2Thinking] = useState(false);
  const [layer2MaxRounds, setLayer2MaxRounds] = useState(5);
  const [layer2TargetPerRound, setLayer2TargetPerRound] = useState(10);
  const [layer2MinNew, setLayer2MinNew] = useState(2);
  const [layer3Selected, setLayer3Selected] = useState([]);
  const [layer3Thinking, setLayer3Thinking] = useState(false);
  const [selectedSpecId, setSelectedSpecId] = useState("");

  // Load config and project list on first render.
  useEffect(() => {
    async function loadBootstrap() {
      try {
        const [configPayload, projectsPayload, healthPayload] = await Promise.all([
          apiFetch("/config"),
          apiFetch("/projects"),
          apiFetch("/health"),
        ]);
        setConfig(configPayload);
        setAppSettings(configPayload);
        setProjects(projectsPayload);
        setStatusMessage(
          healthPayload.ok
            ? "Local model ready."
            : "Local model offline. Generation and research will wait until llama.cpp is available.",
        );
        setActiveProjectId("");
      } catch (loadError) {
        setError(loadError.message);
      }
    }
    loadBootstrap();
  }, []);

  // Refresh the active project snapshot whenever the selected project changes.
  useEffect(() => {
    if (!activeProjectId) {
      setSnapshot(null);
      setProjectModelSettings(null);
      setActiveTab("Layer 0");
      return;
    }
    async function loadSnapshot() {
      try {
        const payload = await apiFetch(`/projects/${activeProjectId}`);
        applySnapshot(payload);
        setSelectedSpecId("");
      } catch (loadError) {
        setError(loadError.message);
      }
    }
    loadSnapshot();
  }, [activeProjectId]);

  // Refresh the project list after create/generation flows that might change ordering.
  async function refreshProjects() {
    const payload = await apiFetch("/projects");
    setProjects(payload);
  }

  // Replace the local snapshot after an API action.
  function applySnapshot(nextSnapshot) {
    setSnapshot(nextSnapshot);
    setProjectModelSettings(nextSnapshot?.project_model_settings || null);
  }

  // Create a new project from the homepage form.
  async function handleCreateProject(event) {
    event.preventDefault();
    setError("");
    const payload = await apiFetch("/projects", {
      method: "POST",
      body: JSON.stringify({
        name: newProjectName,
        idea: newProjectIdea,
      }),
    });
    await refreshProjects();
    setNewProjectName("");
    setNewProjectIdea("");
    setShowCreateProject(false);
    setActiveTab("Layer 0");
    setActiveProjectId(payload.id);
  }

  async function handleSaveModelSettings() {
    if (!appSettings) {
      return;
    }
    setError("");
    setModelSettingsSaveState("saving");
    try {
      const payload = await apiFetch("/config/models", {
        method: "PATCH",
        body: JSON.stringify(appSettings),
      });
      setConfig(payload);
      setAppSettings(payload);
      setModelSettingsSaveState("saved");
      setStatusMessage(`Model settings updated. Chat model: ${payload.llm_model_name}. Embeddings: ${payload.embeddings_model_name}.`);
    } catch (saveError) {
      setModelSettingsSaveState("error");
      setError(saveError.message);
    }
  }

  async function handleSaveProjectModelSettings() {
    if (!activeProjectId || !projectModelSettings) {
      return;
    }
    setError("");
    setProjectSettingsSaveState("saving");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/settings/models`, {
        method: "PATCH",
        body: JSON.stringify(projectModelSettings),
      });
      setProjectModelSettings(payload);
      applySnapshot({ ...snapshot, project_model_settings: payload });
      setProjectSettingsSaveState("saved");
      setStatusMessage("Project model assignments updated.");
    } catch (saveError) {
      setProjectSettingsSaveState("error");
      setError(saveError.message);
    }
  }

  // Save a node edit and then refresh the active snapshot.
  async function handleNodeSave(nodeId, payload) {
    setError("");
    try {
      await apiFetch(`/nodes/${nodeId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
      setStatusMessage("Node updated.");
    } catch (saveError) {
      setError(saveError.message);
      throw saveError;
    }
  }

  async function handleBriefSave(payload) {
    setError("");
    try {
      await apiFetch(`/projects/${activeProjectId}/brief`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
    } catch (saveError) {
      setError(saveError.message);
    }
  }

  async function handlePlanChat(message) {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/brief/chat`, {
        method: "POST",
        body: JSON.stringify({ message }),
      });
      applySnapshot({
        ...snapshot,
        brief: payload.brief,
        brief_conversation: payload.conversation,
      });
      return payload;
    } catch (chatError) {
      setError(chatError.message);
      throw chatError;
    }
  }

  async function handlePublishBrief() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/brief/publish`, {
        method: "POST",
      });
      applySnapshot(payload.snapshot);
      setStatusMessage("Layer 0 published. Local competitor research queued.");
    } catch (publishError) {
      setError(publishError.message);
    }
  }

  async function handleRerunLayer0Research() {
    setError("");
    try {
      await apiFetch(`/projects/${activeProjectId}/research/layer0`, { method: "POST" });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
      setStatusMessage("Layer 0 research queued.");
    } catch (researchError) {
      setError(researchError.message);
    }
  }

  async function handleRerunLayer1Research(pillarIds) {
    setError("");
    try {
      await apiFetch(`/projects/${activeProjectId}/research/layer1`, {
        method: "POST",
        body: JSON.stringify({ pillar_ids: pillarIds }),
      });
      applySnapshot(await apiFetch(`/projects/${activeProjectId}`));
      setStatusMessage("Layer 1 research queued.");
    } catch (researchError) {
      setError(researchError.message);
    }
  }

  // Run Layer 1 broadening through the FastAPI backend.
  async function handleGenerateLayer1() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer1`, {
        method: "POST",
        body: JSON.stringify({
          model_aliases: [],
          thinking_enabled: layer1Thinking,
          max_rounds: layer1MaxRounds,
          target_per_round: layer1TargetPerRound,
          min_new_items_per_round: layer1MinNew,
          stale_rounds_to_stop: 2,
        }),
      });
      setLastSummary(payload.summary);
      applySnapshot(payload.snapshot);
      await refreshProjects();
    } catch (generationError) {
      setError(generationError.message);
    }
  }

  // Run Layer 2 broadening for the selected kept pillars.
  async function handleGenerateLayer2() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer2`, {
        method: "POST",
        body: JSON.stringify({
          pillar_ids: layer2Selected,
          thinking_enabled: layer2Thinking,
          max_rounds: layer2MaxRounds,
          target_per_round: layer2TargetPerRound,
          min_new_items_per_round: layer2MinNew,
          stale_rounds_to_stop: 2,
        }),
      });
      setLastSummary(payload.summaries?.[payload.summaries.length - 1]?.summary || null);
      applySnapshot(payload.snapshot);
    } catch (generationError) {
      setError(generationError.message);
    }
  }

  // Run Layer 3 spec generation for the selected subfeatures.
  async function handleGenerateLayer3() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/generate/layer3`, {
        method: "POST",
        body: JSON.stringify({
          subfeature_ids: layer3Selected,
          thinking_enabled: layer3Thinking,
        }),
      });
      setLastSummary({
        stop_reason: "completed",
        total_rounds: 1,
        created_nodes: payload.created,
        duplicate_candidates: 0,
        filtered_candidates: 0,
        thinking_enabled: layer3Thinking,
        round_summaries: [],
      });
      applySnapshot(payload.snapshot);
    } catch (generationError) {
      setError(generationError.message);
    }
  }

  // Trigger a project export and show the saved file paths.
  async function handleExport() {
    setError("");
    try {
      const payload = await apiFetch(`/projects/${activeProjectId}/export`, {
        method: "POST",
      });
      setStatusMessage(`Exported to ${payload.markdown_path} and ${payload.json_path}`);
    } catch (exportError) {
      setError(exportError.message);
    }
  }

  if (!config) {
    return <div className="app-shell">Loading configuration...</div>;
  }

  const nodes = snapshot?.nodes || [];
  const tree = snapshot?.tree || [];
  const memories = snapshot?.memory || [];
  const brief = snapshot?.brief || null;
  const conversation = snapshot?.brief_conversation || [];
  const researchJobs = snapshot?.research_jobs || [];
  const researchFindings = snapshot?.research_findings || [];
  const project = snapshot?.project || null;
  const pillarChoices = choiceMap(approvedNodes(nodes, "pillar"));
  const subfeatureChoices = choiceMap(approvedNodes(nodes, "subfeature"));
  const specs = nodes.filter((node) => node.node_type === "spec");
  const selectedSpec = specs.find((item) => item.id === selectedSpecId) || specs[0] || null;
  const quarantine = memories.find((item) => item.scope === "layer1" && item.memory_type === "quarantine");
  const layer1Enabled = brief?.status === "published";
  const sortedProjects = sortProjects(projects, sortOrder);

  return (
    <div className={navOpen ? "app-shell nav-open" : "app-shell"}>
      <aside className={navOpen ? "nav-rail open" : "nav-rail closed"}>
        <div className="nav-rail-top">
          <button
            type="button"
            className="rail-icon-button"
            aria-label={navOpen ? "Collapse menu" : "Open menu"}
            onClick={() => setNavOpen((current) => !current)}
          >
            <span className="hamburger-icon" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
          </button>
          {navOpen ? (
            <div className="brand-lockup">
              <strong>SpecForge</strong>
              <span className="muted">{statusMessage}</span>
            </div>
          ) : null}
        </div>
        {navOpen ? (
          <>
            <div className="nav-rail-actions">
              <button type="button" className="rail-action" onClick={() => setShowGuide(true)}>
                Guide
              </button>
              <button type="button" className="rail-action" onClick={() => setShowPrompts(true)}>
                System Prompts
              </button>
              <button type="button" className="rail-action" onClick={() => setShowSettings(true)}>
                Settings
              </button>
            </div>
            <div className="nav-rail-footer muted">
              <p>API: {API_BASE}</p>
              <p>DB: {config.database_backend}</p>
            </div>
          </>
        ) : null}
      </aside>

      <main className="main-content">
        {project ? (
          <div className="page-header">
            <div>
              <button type="button" className="ghost-button" onClick={() => setActiveProjectId("")}>
                Back To Library
              </button>
              <h2>{project.name}</h2>
              <p>{project.idea}</p>
            </div>
            {error ? <div className="error-banner">{error}</div> : null}
          </div>
        ) : error ? <div className="error-banner">{error}</div> : null}
        {!project ? (
          <ProjectHub
            projects={sortedProjects}
            sortOrder={sortOrder}
            onSortOrderChange={setSortOrder}
            onCreateProject={() => setShowCreateProject(true)}
            onOpenProject={(projectId) => {
              setActiveTab("Layer 0");
              setActiveProjectId(projectId);
            }}
          />
        ) : (
          <>
            <div className="tabs">
              {TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={tab === activeTab ? "tab active" : "tab"}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>

            {activeTab === "Layer 0" && brief ? (
              <section className="tab-content">
                <BriefWorkspace
                  brief={brief}
                  conversation={conversation}
                  onSave={handleBriefSave}
                  onChat={handlePlanChat}
                  onPublish={handlePublishBrief}
                />
                <ResearchStatus
                  jobs={researchJobs}
                  onRerunLayer0={handleRerunLayer0Research}
                  onRerunLayer1={handleRerunLayer1Research}
                />
                <MarketPanel findings={researchFindings} />
              </section>
            ) : null}

            {activeTab === "Generate" ? (
              <section className="tab-content">
                <div className="panel">
                  <h3>Layer 1 Broadening</h3>
                  <p className="muted">
                    {layer1Enabled
                      ? "Uses the Layer 1 assignment from this project's Settings tab."
                      : "Publish the Layer 0 brief before broadening Layer 1."}
                  </p>
                  <div className="field-row">
                    <label>
                      Thinking
                      <input type="checkbox" checked={layer1Thinking} onChange={(event) => setLayer1Thinking(event.target.checked)} />
                    </label>
                    <label>
                      Max Rounds
                      <input type="number" value={layer1MaxRounds} onChange={(event) => setLayer1MaxRounds(Number(event.target.value))} />
                    </label>
                    <label>
                      Target per Round
                      <input
                        type="number"
                        value={layer1TargetPerRound}
                        onChange={(event) => setLayer1TargetPerRound(Number(event.target.value))}
                      />
                    </label>
                    <label>
                      Min New
                      <input type="number" value={layer1MinNew} onChange={(event) => setLayer1MinNew(Number(event.target.value))} />
                    </label>
                  </div>
                  <button type="button" onClick={handleGenerateLayer1} disabled={!layer1Enabled}>
                    Broaden Layer 1
                  </button>
                </div>

                <CheckboxList
                  title="Layer 2 Eligible Pillars"
                  options={pillarChoices}
                  selectedValues={layer2Selected}
                  onChange={setLayer2Selected}
                />
                <div className="panel">
                  <h3>Layer 2 Broadening</h3>
                  <div className="field-row">
                    <label>
                      Thinking
                      <input type="checkbox" checked={layer2Thinking} onChange={(event) => setLayer2Thinking(event.target.checked)} />
                    </label>
                    <label>
                      Max Rounds
                      <input type="number" value={layer2MaxRounds} onChange={(event) => setLayer2MaxRounds(Number(event.target.value))} />
                    </label>
                    <label>
                      Target per Round
                      <input
                        type="number"
                        value={layer2TargetPerRound}
                        onChange={(event) => setLayer2TargetPerRound(Number(event.target.value))}
                      />
                    </label>
                    <label>
                      Min New
                      <input type="number" value={layer2MinNew} onChange={(event) => setLayer2MinNew(Number(event.target.value))} />
                    </label>
                  </div>
                  <button type="button" onClick={handleGenerateLayer2} disabled={!layer2Selected.length}>
                    Broaden Layer 2
                  </button>
                </div>

                <CheckboxList
                  title="Layer 3 Eligible Subfeatures"
                  options={subfeatureChoices}
                  selectedValues={layer3Selected}
                  onChange={setLayer3Selected}
                />
                <div className="panel">
                  <h3>Layer 3 Specs</h3>
                  <label>
                    Thinking
                    <input type="checkbox" checked={layer3Thinking} onChange={(event) => setLayer3Thinking(event.target.checked)} />
                  </label>
                  <button type="button" onClick={handleGenerateLayer3} disabled={!layer3Selected.length}>
                    Generate Layer 3 Specs
                  </button>
                </div>
                <GenerationSummary summary={lastSummary} />
              </section>
            ) : null}

            {activeTab === "Tree" ? (
              <section className="tab-content">
                {tree.length || brief ? (
                  <TreeDashboard
                    project={project}
                    brief={brief}
                    tree={tree}
                    findings={researchFindings}
                    onSaveNode={handleNodeSave}
                  />
                ) : (
                  <div className="panel">
                    <h3>Product Map</h3>
                    <p className="muted">No generated nodes yet.</p>
                  </div>
                )}
              </section>
            ) : null}

            {activeTab === "Review" ? (
              <section className="tab-content">
                {nodes.length ? nodes.map((node) => (
                  <NodeEditor
                    key={node.id}
                    node={node}
                    onSave={handleNodeSave}
                    findings={researchFindings}
                    onRerunResearch={handleRerunLayer1Research}
                  />
                )) : <p className="muted">Nothing to review yet.</p>}
              </section>
            ) : null}

            {activeTab === "Specs" ? (
              <section className="tab-content">
                <div className="panel">
                  <h3>Spec Viewer</h3>
                  {selectedSpec ? (
                    <>
                      <label>
                        Spec
                        <select value={selectedSpec.id} onChange={(event) => setSelectedSpecId(event.target.value)}>
                          {specs.map((spec) => (
                            <option key={spec.id} value={spec.id}>
                              {spec.title}
                            </option>
                          ))}
                        </select>
                      </label>
                      <p>{selectedSpec.description}</p>
                      <pre>{JSON.stringify(selectedSpec.json_payload, null, 2)}</pre>
                    </>
                  ) : (
                    <p className="muted">No specs generated yet.</p>
                  )}
                </div>
              </section>
            ) : null}

            {activeTab === "Settings" ? (
              <ProjectSettingsTab
                settings={projectModelSettings}
                config={config}
                saveState={projectSettingsSaveState}
                onChange={setProjectModelSettings}
                onSave={handleSaveProjectModelSettings}
              />
            ) : null}

            {activeTab === "Export" ? (
              <section className="tab-content">
                <div className="panel">
                  <h3>Export</h3>
                  <button type="button" onClick={handleExport}>
                    Export Markdown and JSON
                  </button>
                </div>
                <div className="panel">
                  <h3>Generation Memory</h3>
                  <pre>{JSON.stringify(memories, null, 2)}</pre>
                </div>
                {quarantine ? (
                  <div className="panel">
                    <h3>Layer 1 Quarantine</h3>
                    <pre>{JSON.stringify(quarantine.content, null, 2)}</pre>
                  </div>
                ) : null}
              </section>
            ) : null}
          </>
        )}
      </main>
      {showCreateProject ? (
        <CreateProjectModal
          name={newProjectName}
          idea={newProjectIdea}
          onNameChange={setNewProjectName}
          onIdeaChange={setNewProjectIdea}
          onSubmit={handleCreateProject}
          onClose={() => setShowCreateProject(false)}
        />
      ) : null}
      {showSettings ? (
        <AppSettingsModal
          settings={appSettings}
          config={config}
          saveState={modelSettingsSaveState}
          onChange={setAppSettings}
          onSave={handleSaveModelSettings}
          onClose={() => setShowSettings(false)}
        />
      ) : null}
      {showPrompts ? (
        <ModalFrame
          title="System Prompts"
          subtitle="Edit the shared prompt templates here. These edits apply to new projects created after you save."
          onClose={() => setShowPrompts(false)}
          className="prompts-modal"
        >
          <PromptCatalogEditor
            settings={appSettings}
            onChange={setAppSettings}
            onSave={handleSaveModelSettings}
            saveState={modelSettingsSaveState}
          />
        </ModalFrame>
      ) : null}
      {showGuide ? <GuideModal onClose={() => setShowGuide(false)} /> : null}
    </div>
  );
}
