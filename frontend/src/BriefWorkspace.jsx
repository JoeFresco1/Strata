import { useEffect, useRef, useState } from "react";
import { displayStatusLabel } from "./workspace/WorkspacePage";

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

function collapseLegacyDuplicatePairs(conversation) {
  // Suppress already-persisted adjacent duplicate exchanges while new requests use durable IDs.
  const visible = [];
  for (let index = 0; index < conversation.length; index += 1) {
    const current = conversation[index];
    const next = conversation[index + 1];
    const priorUser = visible[visible.length - 2];
    const priorAssistant = visible[visible.length - 1];
    const repeatsPair = current?.role === "user"
      && next?.role === "assistant"
      && priorUser?.role === "user"
      && priorAssistant?.role === "assistant"
      && current.content === priorUser.content
      && next.content === priorAssistant.content;
    if (repeatsPair) {
      index += 1;
      continue;
    }
    visible.push(current);
  }
  return visible;
}

function compactPreview(value, limit = 220) {
  const text = String(value || "");
  if (text.length <= limit) return text;
  return `${text.slice(0, limit - 3).trim()}...`;
}

function BriefWorkspace({ brief, conversation, onSave, onChat, locked = false, unlocked = false, onUnlock, compact = false }) {
  const [mode, setMode] = useState("AI Chat");
  const [form, setForm] = useState(brief);
  const [message, setMessage] = useState("");
  const [planState, setPlanState] = useState("idle");
  const [snapshotOpen, setSnapshotOpen] = useState(!compact);
  const chatLogRef = useRef(null);
  const sendingRef = useRef(false);

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
  const visibleConversation = collapseLegacyDuplicatePairs(conversation);
  const suggestions = guidance?.next_questions?.length ? guidance.next_questions : planSuggestionsFromBrief(payload);
  const visibleSuggestions = compact ? suggestions.slice(0, 2) : suggestions;
  const isPublished = brief.status === "published";
  const readOnly = locked && !unlocked;

  // Sends a Plan-mode message and lets the backend extract structured brief fields.
  async function sendPlanMessage(nextMessage) {
    const clean = nextMessage.trim();
    if (!clean || sendingRef.current) {
      return;
    }
    sendingRef.current = true;
    setPlanState("sending");
    try {
      const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
      await onChat(clean, requestId);
      setMessage("");
      setPlanState("idle");
    } catch {
      setPlanState("error");
    } finally {
      sendingRef.current = false;
    }
  }

  return (
    <div className={compact ? "panel brief-workspace compact" : "panel brief-workspace"}>
      <div className="panel-header">
        <div>
          <h3>Layer 0 Brief</h3>
          <span className={`status-pill ${brief.status}`}>{displayStatusLabel(brief.status)}</span>
        </div>
        <div className="segmented">
          {["AI Chat", "Form"].map((item) => (
            <button key={item} type="button" className={mode === item ? "active" : ""} onClick={() => setMode(item)}>
              {item}
            </button>
          ))}
        </div>
      </div>

      {mode === "AI Chat" && readOnly ? (
        <div className="published-brief-summary">
          <div>
            <span className="status-pill published">Layer 0 locked</span>
            <h4>{payload.product_idea || "Published project brief"}</h4>
            <p className="muted">This published product plan is active in downstream layers. Unlock only when the product direction truly needs to change.</p>
          </div>
          <button type="button" className="secondary-button" onClick={onUnlock}>Unlock Layer 0</button>
        </div>
      ) : null}

      {mode === "AI Chat" && !readOnly ? (
        <div className="plan-workspace">
          <div className="plan-chat-panel">
            <div className="plan-mode-header">
              <div>
                <h4>Product Plan Conversation</h4>
                <p className="muted">
                  {isPublished
                    ? "Layer 0 is unlocked for this session. Changes may require downstream review."
                    : "Use this like a working session with an intake agent. The assistant should help discover the brief, ask follow-up questions, and keep the draft moving toward publish."}
                </p>
              </div>
              <div className="plan-chip-row">
                {visibleSuggestions.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="preset-chip"
                    title={compact ? suggestion : undefined}
                    onClick={() => {
                      setMessage(suggestion);
                    }}
                  >
                    {compact ? compactPreview(suggestion, 76) : suggestion}
                  </button>
                ))}
              </div>
            </div>

            <div ref={chatLogRef} className="chat-log plan-chat-log">
              {!visibleConversation.length ? (
                <div className="chat-turn assistant starter">
                  <div className="chat-turn-bubble">
                    <strong>Strata</strong>
                    <p>
                      I can help shape the draft brief before anything gets published. Start with the product idea,
                      the user problem, or just the rough direction, and I&apos;ll pull structure out as we go.
                    </p>
                    <p className="muted">A good first turn is usually the product idea, target user, or what feels most uncertain.</p>
                  </div>
                </div>
              ) : null}
              {visibleConversation.map((turn) => {
                const updates = extractedUpdateBadges(turn);
                return (
                  <div key={turn.id} className={`chat-turn ${turn.role}`}>
                    <div className="chat-turn-bubble">
                      <div className="chat-turn-head">
                        <strong>{turn.role === "assistant" ? "Strata" : "You"}</strong>
                        {updates.length ? <span className="chat-turn-meta">Updated: {updates.join(", ")}</span> : null}
                      </div>
                      <p title={compact ? turn.content : undefined}>{compact ? compactPreview(turn.content) : turn.content}</p>
                    </div>
                  </div>
                );
              })}
              {planState === "sending" ? (
                <div className="chat-turn assistant loading">
                  <div className="chat-turn-bubble">
                    <strong>Strata</strong>
                    <p>Updating the draft brief and preparing the next question.</p>
                  </div>
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
                <p className="muted plan-composer-note">
                  {isPublished
                    ? "Layer 0 is unlocked for this session. Save carefully and review downstream layers after changes."
                    : "The draft updates continuously. Layer 1 stays locked until this version is published."}
                </p>
                <button type="submit" disabled={planState === "sending" || !message.trim()}>
                  {planState === "sending" ? "Thinking..." : "Send"}
                </button>
              </div>
            </form>
          </div>

          {!compact ? <aside className={snapshotOpen ? "plan-brief-sidebar" : "plan-brief-sidebar collapsed"}>
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
                    <h4>{isPublished ? "Published Brief Snapshot" : "Draft Brief Snapshot"}</h4>
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
                      <li>The main brief fields are populated. Use AI Chat to pressure test the direction before publishing.</li>
                    )}
                  </ul>
                </div>
              </>
            ) : (
              <div className="plan-sidebar-collapsed-spacer" aria-hidden="true" />
            )}
          </aside> : null}
        </div>
      ) : null}

      {mode === "Form" ? (
        <div className="brief-grid layer0-brief-form">
          <label>
            Product Idea
            <textarea disabled={readOnly} value={payload.product_idea} onChange={(event) => updateField("product_idea", event.target.value)} rows={4} />
          </label>
          <label>
            Known Competitors
            <textarea disabled={readOnly} value={listToText(payload.known_competitors)} onChange={(event) => updateField("known_competitors", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Target Users
            <textarea disabled={readOnly} value={payload.target_users} onChange={(event) => updateField("target_users", event.target.value)} rows={3} />
          </label>
          <label>
            Constraints
            <textarea disabled={readOnly} value={payload.constraints} onChange={(event) => updateField("constraints", event.target.value)} rows={3} />
          </label>
          <label>
            Goals
            <textarea disabled={readOnly} value={listToText(payload.goals)} onChange={(event) => updateField("goals", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Preferred Directions
            <textarea disabled={readOnly} value={listToText(payload.preferred_directions)} onChange={(event) => updateField("preferred_directions", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Rejected Directions
            <textarea disabled={readOnly} value={listToText(payload.rejected_directions)} onChange={(event) => updateField("rejected_directions", textToList(event.target.value))} rows={4} />
          </label>
          <label>
            Notes
            <textarea disabled={readOnly} value={payload.notes} onChange={(event) => updateField("notes", event.target.value)} rows={4} />
          </label>
          <div className="layer0-brief-actions">
            {readOnly ? <button type="button" className="secondary-button" onClick={onUnlock}>Unlock Layer 0</button> : <button type="button" className="secondary-button" onClick={() => onSave(payload)}>Save Brief</button>}
          </div>
        </div>
      ) : null}

      {isPublished ? (
        <div className="publish-row published-state">
          <span className="status-pill published">{readOnly ? "Locked downstream snapshot" : "Unlocked for editing"}</span>
          <p className="muted">{readOnly ? "Downstream generation uses this published version until you explicitly unlock Layer 0." : "Changes may require downstream review after saving."}</p>
        </div>
      ) : null}
    </div>
  );
}


export default BriefWorkspace;
