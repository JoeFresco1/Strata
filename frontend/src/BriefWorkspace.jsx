import { useEffect, useRef, useState } from "react";
import { displayStatusLabel } from "./workspace/WorkspacePage";

function textToList(value) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToText(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

function extractedUpdateBadges(turn) {
  const updates = turn.extracted_updates?.updates || turn.extracted_updates?.brief_updates || {};
  return Object.entries(updates)
    .filter(([, value]) => {
      if (Array.isArray(value)) return value.length;
      return Boolean(String(value || "").trim());
    })
    .map(([key]) => key.replaceAll("_", " "));
}

function latestPlanGuidance(conversation) {
  const assistantTurns = conversation.filter((turn) => turn.role === "assistant");
  const latest = assistantTurns[assistantTurns.length - 1];
  return latest?.extracted_updates?.plan_guidance || null;
}

function collapseLegacyDuplicatePairs(conversation) {
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

function normalizeBriefPayload(source = {}) {
  return {
    product_idea: source.product_idea || "",
    problem: source.problem || "",
    target_users: source.target_users || "",
    constraints: source.constraints || "",
    goals: Array.isArray(source.goals) ? source.goals : textToList(source.goals || ""),
    known_competitors: Array.isArray(source.known_competitors) ? source.known_competitors : textToList(source.known_competitors || ""),
    preferred_directions: Array.isArray(source.preferred_directions) ? source.preferred_directions : textToList(source.preferred_directions || ""),
    rejected_directions: Array.isArray(source.rejected_directions) ? source.rejected_directions : textToList(source.rejected_directions || ""),
    notes: source.notes || "",
  };
}

function briefProgressItems(brief) {
  return [
    {
      label: "Product summary",
      ready: Boolean(brief?.product_idea?.trim()),
      summary: brief?.product_idea?.trim() || "Still open",
    },
    {
      label: "Problem",
      ready: Boolean(brief?.problem?.trim()),
      summary: brief?.problem?.trim() || "Still open",
    },
    {
      label: "Target users",
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

function actionPrompts(brief) {
  const openGoals = !brief.goals?.length;
  const openCompetitors = !brief.known_competitors?.length;
  const openProblem = !brief.problem?.trim();
  return {
    weakSpots: "Review the current brief, point out the weakest spots, and tell me what I should tighten before publishing.",
    nextQuestion: "Ask me the next most important question to make this brief publish-ready.",
    improveClarity: openProblem
      ? "Help me clarify the product idea and the exact problem this product should solve first."
      : "Improve the clarity of this brief and rewrite any muddy parts into sharper product language.",
    generateMissing: openGoals || openCompetitors
      ? "Generate draft content for the missing brief fields based on what we already know, and clearly flag assumptions."
      : "Regenerate the brief into a tighter, cleaner version and flag any missing or weak fields.",
    regenerate: "Regenerate the current brief into a clearer, tighter draft and call out anything that still needs review.",
  };
}

const MODE_OPTIONS = [
  { id: "Form", label: "Guided form" },
  { id: "AI Chat", label: "AI chat" },
];

const FORM_FIELDS = [
  { key: "product_idea", label: "Product summary", rows: 4 },
  { key: "target_users", label: "Target users", rows: 4 },
  { key: "problem", label: "Problem", rows: 4 },
  { key: "constraints", label: "Constraints", rows: 4 },
  { key: "goals", label: "Goals", rows: 4, list: true },
  { key: "known_competitors", label: "Competitors", rows: 4, list: true },
  { key: "preferred_directions", label: "Preferred directions", rows: 4, list: true },
  { key: "rejected_directions", label: "Rejected directions", rows: 4, list: true },
];

export default function BriefWorkspace({
  brief,
  conversation,
  onSave,
  onChat,
  onProceed,
  canProceed = false,
  proceedDisabledReason = "",
  compact = false,
}) {
  const [mode, setMode] = useState("Form");
  const [form, setForm] = useState(() => normalizeBriefPayload(brief));
  const [message, setMessage] = useState("");
  const [planState, setPlanState] = useState("idle");
  const chatLogRef = useRef(null);
  const sendingRef = useRef(false);
  const conversationItems = Array.isArray(conversation) ? conversation : [];

  useEffect(() => {
    setForm(normalizeBriefPayload(brief));
  }, [brief]);

  useEffect(() => {
    if (!chatLogRef.current) return;
    chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
  }, [conversationItems.length, planState]);

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  const payload = normalizeBriefPayload(form);
  const savedPayload = normalizeBriefPayload(brief);
  const isDirty = JSON.stringify(payload) !== JSON.stringify(savedPayload);
  const visibleConversation = collapseLegacyDuplicatePairs(conversationItems);
  const guidance = latestPlanGuidance(conversationItems);
  const progressItems = briefProgressItems(savedPayload);
  const prompts = actionPrompts(savedPayload);
  const isPublished = brief?.status === "published";

  async function sendPlanMessage(nextMessage) {
    const clean = nextMessage.trim();
    if (!clean || sendingRef.current) return;
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

  function queuePrompt(prompt, nextMode = "AI Chat") {
    setMode(nextMode);
    setMessage(prompt);
  }

  return (
    <div className={`panel brief-workspace brief-editor-shell${compact ? " compact" : ""}`}>
      <div className="brief-editor-header">
        <div>
          <span className="workspace-eyebrow">Layer 0 brief editor</span>
          <h3>Brief editor</h3>
          <p className="muted">Use the form for canonical edits and AI chat for refinement. The saved brief on the right stays the source of truth.</p>
        </div>
        <div className="brief-editor-header-side">
          <span className={`status-pill ${brief?.status || "draft"}`}>{displayStatusLabel(brief?.status)}</span>
          <div className="segmented brief-mode-toggle" aria-label="Brief editor mode">
            {MODE_OPTIONS.map((item) => (
              <button key={item.id} type="button" className={mode === item.id ? "active" : ""} onClick={() => setMode(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <section className="brief-editor-section brief-actions-toolbar" aria-label="Brief actions">
        <span className="workspace-card-label">Actions</span>
        <div className="brief-suggested-actions">
          <button type="button" className="secondary-button" onClick={() => queuePrompt(prompts.weakSpots)}>Review weak spots</button>
          <button type="button" className="secondary-button" onClick={() => queuePrompt(prompts.nextQuestion)}>Ask next question</button>
          <button type="button" className="secondary-button" onClick={() => queuePrompt(prompts.improveClarity)}>Improve clarity</button>
          <button type="button" onClick={() => queuePrompt(prompts.generateMissing)}>Generate missing brief fields</button>
        </div>
      </section>

      <div className={`brief-editor-notice ${isDirty ? "warning" : "success"}`}>
        <strong>{isDirty ? "Unsaved edits are local to the editor." : "Brief Preview matches the saved brief."}</strong>
        <span>{isDirty ? "Use Save brief to update the canonical brief. The preview panel still shows the last saved version." : "The right-side preview is showing the current saved source-of-truth brief."}</span>
      </div>

      {isPublished ? (
        <div className="brief-editor-notice warning">
          <strong>This Layer 0 brief is published.</strong>
          <span>Saving new edits will move it back to draft, and downstream layers may need review after you republish.</span>
        </div>
      ) : null}

      {guidance ? (
        <section className="brief-editor-section brief-guidance-panel">
          <div className="brief-section-head">
            <div>
              <span className="workspace-card-label">Current AI focus</span>
              <strong>{guidance.focus_area.replaceAll("_", " ")}</strong>
            </div>
            <span className="status-pill">{guidance.confidence}</span>
          </div>
          <p className="muted">{guidance.recap}</p>
          {guidance.next_questions?.length ? (
            <div className="brief-guidance-questions">
              {guidance.next_questions.map((question) => (
                <button key={question} type="button" className="preset-chip" onClick={() => queuePrompt(question)}>
                  {compact ? compactPreview(question, 80) : question}
                </button>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {mode === "AI Chat" ? (
        <section className="brief-editor-section brief-chat-section">
          <div className="brief-section-head">
            <div>
              <span className="workspace-card-label">AI refinement</span>
              <p className="muted">Use chat to refine, challenge, or tighten the brief. Structured updates still flow into the same canonical Layer 0 brief after save.</p>
            </div>
          </div>

          <div ref={chatLogRef} className="chat-log plan-chat-log brief-chat-log">
            {!visibleConversation.length ? (
              <div className="chat-turn assistant starter">
                <div className="chat-turn-bubble">
                  <strong>Strata</strong>
                  <p>Start with the product idea, the user problem, or the part of the brief that still feels weak. I&apos;ll help refine the brief without replacing the structured form.</p>
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
                  <p>Updating the brief and preparing the next refinement step.</p>
                </div>
              </div>
            ) : null}
          </div>

          <form
            className="plan-composer brief-chat-composer"
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
                placeholder="Refine the brief, answer a follow-up, or ask Strata to tighten the product definition."
              />
            </label>
            <div className="brief-chat-composer-actions">
              <p className="muted">Chat helps refine the brief, but the saved Layer 0 brief remains the canonical source for downstream work.</p>
              <button type="submit" disabled={planState === "sending" || !message.trim()}>
                {planState === "sending" ? "Thinking..." : "Send"}
              </button>
            </div>
          </form>
        </section>
      ) : (
        <section className="brief-editor-section">
          <div className="brief-section-head">
            <div>
              <span className="workspace-card-label">Structured brief</span>
              <p className="muted">Edit the core Layer 0 fields directly. Use one line per item for list fields.</p>
            </div>
          </div>

          <div className="brief-grid layer0-brief-form canonical-brief-form">
            {FORM_FIELDS.map((field) => (
              <label key={field.key} className={field.key === "product_idea" || field.key === "problem" ? "brief-field-span" : ""}>
                {field.label}
                <textarea
                  value={field.list ? listToText(payload[field.key]) : payload[field.key]}
                  onChange={(event) => updateField(field.key, field.list ? textToList(event.target.value) : event.target.value)}
                  rows={field.rows}
                />
              </label>
            ))}
            <label className="brief-field-span">
              Internal notes (optional)
              <textarea value={payload.notes} onChange={(event) => updateField("notes", event.target.value)} rows={3} />
            </label>
          </div>
        </section>
      )}

      <section className="brief-editor-section brief-progress-panel">
        <div className="brief-section-head">
          <div>
            <span className="workspace-card-label">Brief coverage</span>
            <p className="muted">A quick read on what the saved brief already covers well.</p>
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
      </section>

      <div className="brief-editor-footer">
        <div className="brief-editor-primary-actions">
          <button type="button" onClick={() => onSave(payload)} disabled={!isDirty}>
            Save brief
          </button>
        </div>
        <div className="brief-editor-secondary-actions">
          <button type="button" className="secondary-button" onClick={() => queuePrompt(prompts.regenerate)}>
            Regenerate brief
          </button>
          <button type="button" className="secondary-button" onClick={onProceed} disabled={!canProceed} title={!canProceed ? proceedDisabledReason : undefined}>
            Proceed to L1 Pillars
          </button>
        </div>
      </div>
    </div>
  );
}
