import { useEffect, useRef, useState } from "react";

// Converts multiline text fields into the array shape expected by the API.
function textToList(value) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

// Converts persisted array fields back into editable textarea text.
function listToText(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

// Builds the readiness checklist shown beside the Layer 0 brief editor.
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

// Chooses contextual Plan-mode starter prompts from the current brief gaps.
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
  return [
    "Review the brief and tell me what is still weak.",
    "Ask me the next most important question before Layer 1.",
    "Challenge the assumptions in this product direction.",
  ];
}

// Extracts which fields the assistant updated during a Plan-mode exchange.
function extractedUpdateBadges(turn) {
  const updates = turn.extracted_updates?.updates || {};
  return Object.entries(updates)
    .filter(([, value]) => {
      if (Array.isArray(value)) return value.length;
      return Boolean(String(value || "").trim());
    })
    .map(([key]) => key.replaceAll("_", " "));
}

// Returns the latest assistant guidance block from the Layer 0 conversation.
function latestPlanGuidance(conversation) {
  const assistantTurns = conversation.filter((turn) => turn.role === "assistant");
  const latest = assistantTurns[assistantTurns.length - 1];
  return latest?.extracted_updates?.plan_guidance || null;
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

  // Keeps form state local until the user saves or publishes the brief.
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

  // Sends a Plan-mode message and lets the backend extract structured brief fields.
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
                  <strong>Strata</strong>
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
                      <strong>{turn.role === "assistant" ? "Strata" : "You"}</strong>
                      {updates.length ? <span className="chat-turn-meta">Updated: {updates.join(", ")}</span> : null}
                    </div>
                    <p>{turn.content}</p>
                  </div>
                );
              })}
              {planState === "sending" ? (
                <div className="chat-turn assistant loading">
                  <strong>Strata</strong>
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


export default BriefWorkspace;
