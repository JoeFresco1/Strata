import { useEffect, useMemo, useRef, useState } from "react";
import { displayStatusLabel } from "./workspace/WorkspacePage";
import {
  isNearConversationBottom,
  LAYER0_WAITING_PHRASES,
  safeAssistantContent,
  shouldSubmitComposer,
} from "./layer0Conversation";

function textToList(value) {
  return String(value || "").split("\n").map((item) => item.trim()).filter(Boolean);
}

function listToText(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

function normalizeBriefPayload(source = {}) {
  return {
    product_idea: source.product_idea || "",
    problem: source.problem || "",
    target_users: source.target_users || "",
    constraints: source.constraints || "",
    goals: Array.isArray(source.goals) ? source.goals : textToList(source.goals),
    known_competitors: Array.isArray(source.known_competitors) ? source.known_competitors : textToList(source.known_competitors),
    preferred_directions: Array.isArray(source.preferred_directions) ? source.preferred_directions : textToList(source.preferred_directions),
    rejected_directions: Array.isArray(source.rejected_directions) ? source.rejected_directions : textToList(source.rejected_directions),
    notes: source.notes || "",
  };
}

function latestPlanGuidance(conversation) {
  return [...conversation].reverse().find((turn) => turn.role === "assistant")?.extracted_updates?.plan_guidance || null;
}

function visibleConversation(conversation) {
  const visible = [];
  conversation.forEach((turn) => {
    const prior = visible[visible.length - 1];
    if (prior?.role === turn.role && prior?.request_id && prior.request_id === turn.request_id) return;
    visible.push(turn);
  });
  return visible;
}

function formatTimestamp(value) {
  if (!value) return "Now";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(parsed);
}

function fieldLabel(value) {
  return String(value || "").replaceAll("_", " ");
}

function displayProposalValue(value) {
  return Array.isArray(value) ? value.join("\n") : String(value || "Not captured yet");
}

const MODE_OPTIONS = [
  { id: "AI Chat", label: "AI conversation" },
  { id: "Form", label: "Guided form" },
];

const STARTERS = [
  "Help me define the user problem",
  "Challenge this product idea",
  "Identify missing target users",
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

function ActivitySummary({ steps = [] }) {
  if (!steps.length) return null;
  return (
    <details className="layer0-activity-summary">
      <summary>Show activity</summary>
      <ul>{steps.map((step) => <li key={step}>{step}</li>)}</ul>
    </details>
  );
}

function ProposalCard({ turn, onDecision }) {
  const proposal = turn.extracted_updates?.proposal;
  const [reviewing, setReviewing] = useState(false);
  const [editingField, setEditingField] = useState("");
  const [editedValues, setEditedValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!proposal?.fields?.length) return null;
  const pending = ["pending", "partially_applied"].includes(proposal.status);

  async function decide(decision, selectedFields = []) {
    // Sends only the fields the user explicitly reviewed and keeps failures inline.
    setBusy(true);
    setError("");
    try {
      await onDecision(turn.id, {
        decision,
        selected_fields: selectedFields,
        edited_values: editedValues,
        expected_state_token: proposal.base_state_token,
        request_id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      });
    } catch (decisionError) {
      setError(decisionError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`layer0-proposal-card ${proposal.status}`} aria-label="Proposed brief update">
      <div className="layer0-proposal-head">
        <div>
          <span className="workspace-card-label">Proposed brief update</span>
          <strong>{proposal.fields.length} saved {proposal.fields.length === 1 ? "field" : "fields"} could change</strong>
        </div>
        <span className={`status-pill ${proposal.status}`}>{fieldLabel(proposal.status)}</span>
      </div>
      {(reviewing || !pending) ? (
        <div className="layer0-proposal-fields">
          {proposal.fields.map((item) => {
            const applied = proposal.applied_fields?.includes(item.field);
            return (
              <article key={item.field} className={`layer0-proposal-field${applied ? " applied" : ""}`}>
                <div className="layer0-proposal-field-head">
                  <strong>{fieldLabel(item.field)}</strong>
                  <span>{applied ? "Applied" : item.operation}</span>
                </div>
                <div className="layer0-proposal-comparison">
                  <div><span>Current</span><p>{displayProposalValue(item.current_value)}</p></div>
                  <div><span>Proposed</span><p>{displayProposalValue(item.proposed_value)}</p></div>
                </div>
                <p className="muted">{item.reason}</p>
                {editingField === item.field ? (
                  <textarea
                    value={editedValues[item.field] ?? displayProposalValue(item.proposed_value)}
                    onChange={(event) => setEditedValues((current) => ({ ...current, [item.field]: event.target.value }))}
                    rows={4}
                    aria-label={`Edit proposed ${fieldLabel(item.field)}`}
                  />
                ) : null}
                {pending && !applied ? (
                  <div className="layer0-proposal-field-actions">
                    <button type="button" onClick={() => decide("apply", [item.field])} disabled={busy}>Apply</button>
                    <button type="button" className="secondary-button" onClick={() => setEditingField(item.field)} disabled={busy}>Edit before applying</button>
                    <button type="button" className="text-button" onClick={() => setReviewing(true)} disabled={busy}>Skip</button>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : null}
      {proposal.status === "stale" ? (
        <div className="inline-conversation-error" role="alert">
          <strong>The saved brief changed before this proposal could be applied.</strong>
          <span>Reload the current brief, compare the values above, or ask Strata to regenerate the proposal.</span>
        </div>
      ) : null}
      {error ? <div className="inline-conversation-error" role="alert">{error}</div> : null}
      {pending ? (
        <div className="layer0-proposal-actions">
          <button type="button" onClick={() => decide("apply")} disabled={busy}>Apply all</button>
          <button type="button" className="secondary-button" onClick={() => setReviewing((current) => !current)} disabled={busy}>
            {reviewing ? "Hide field review" : "Review individually"}
          </button>
          <button type="button" className="text-button" onClick={() => decide("dismiss")} disabled={busy}>Dismiss</button>
        </div>
      ) : null}
    </section>
  );
}

function ChatTurn({ turn, onProposalDecision, onRetry }) {
  const status = turn.extracted_updates?.stream_status || "completed";
  const activity = turn.extracted_updates?.activity || [];
  const content = turn.role === "assistant" ? safeAssistantContent(turn.content) : turn.content;
  return (
    <article className={`layer0-message ${turn.role} ${status}`} aria-label={`${turn.role} message`}>
      <div className="layer0-message-meta">
        <strong>{turn.role === "assistant" ? "Strata" : turn.role === "system" ? "Workflow" : "You"}</strong>
        <span>{formatTimestamp(turn.created_at)}</span>
        {status !== "completed" ? <span className={`message-status ${status}`}>{status}</span> : null}
      </div>
      {content ? <div className="layer0-message-content">{content}</div> : null}
      {turn.role === "assistant" ? <ActivitySummary steps={activity} /> : null}
      {turn.role === "assistant" && status === "failed" ? (
        <div className="inline-conversation-error" role="alert">
          <span>{turn.extracted_updates?.error?.message || "The model response failed."}</span>
          <button type="button" className="secondary-button" onClick={() => onRetry(turn)}>Retry response</button>
        </div>
      ) : null}
      {turn.role === "assistant" && status === "stopped" ? <p className="message-footnote">Stopped by you. The partial response was preserved.</p> : null}
      {turn.role === "assistant" ? <ProposalCard turn={turn} onDecision={onProposalDecision} /> : null}
    </article>
  );
}

export default function BriefWorkspace({
  brief,
  conversation,
  onSave,
  onChat,
  onStopChat,
  onProposalDecision,
  compact = false,
}) {
  const [mode, setMode] = useState("AI Chat");
  const [form, setForm] = useState(() => normalizeBriefPayload(brief));
  const [message, setMessage] = useState("");
  const [planState, setPlanState] = useState("idle");
  const [pendingTurn, setPendingTurn] = useState(null);
  const [waitingPhraseIndex, setWaitingPhraseIndex] = useState(0);
  const [autoScroll, setAutoScroll] = useState(true);
  const [streamError, setStreamError] = useState("");
  const chatLogRef = useRef(null);
  const composerRef = useRef(null);
  const activeRequestRef = useRef(null);
  const ignoreDeltasRef = useRef(false);
  const conversationItems = useMemo(() => visibleConversation(Array.isArray(conversation) ? conversation : []), [conversation]);
  const guidance = latestPlanGuidance(conversationItems);
  const savedPayload = normalizeBriefPayload(brief);
  const payload = normalizeBriefPayload(form);
  const isDirty = JSON.stringify(payload) !== JSON.stringify(savedPayload);
  const isGenerating = ["connecting", "streaming"].includes(planState);
  const conversationStarted = conversationItems.length > 0 || Boolean(pendingTurn);

  useEffect(() => setForm(normalizeBriefPayload(brief)), [brief]);

  useEffect(() => {
    // Rotates lightweight waiting copy only before the first provider chunk arrives.
    if (planState !== "connecting") return undefined;
    const timer = window.setInterval(() => {
      setWaitingPhraseIndex((current) => (current + 1) % LAYER0_WAITING_PHRASES.length);
    }, 2400);
    return () => window.clearInterval(timer);
  }, [planState]);

  useEffect(() => {
    // Follows new content only while the reader remains near the bottom.
    if (!autoScroll || !chatLogRef.current) return;
    chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
  }, [conversationItems.length, pendingTurn?.content, planState, autoScroll]);

  useEffect(() => () => activeRequestRef.current?.controller.abort(), []);

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function handleStreamEvent(event) {
    // Projects typed stream events into one temporary assistant turn until persistence refreshes.
    if (event.type === "activity") {
      setPendingTurn((current) => ({ ...(current || {}), activity: event.steps || [] }));
      return;
    }
    if (event.type === "delta") {
      if (ignoreDeltasRef.current) return;
      setPlanState("streaming");
      setPendingTurn((current) => ({ ...(current || {}), content: `${current?.content || ""}${event.content || ""}` }));
      return;
    }
    if (["complete", "completed", "stopped"].includes(event.type)) {
      setPlanState(event.type === "stopped" ? "stopped" : "idle");
      if (event.turn) setPendingTurn((current) => ({ ...(current || {}), ...event.turn, optimistic: true }));
      return;
    }
    if (event.type === "error") {
      setPlanState("error");
      setStreamError(event.message || "The model response failed.");
      if (event.turn) setPendingTurn((current) => ({ ...(current || {}), ...event.turn, optimistic: true }));
    }
  }

  async function sendPlanMessage(nextMessage, options = {}) {
    // Starts one idempotent stream and leaves the original user turn intact on retry.
    const clean = nextMessage.trim();
    if (!clean || isGenerating) return;
    const requestId = options.requestId || globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const controller = new AbortController();
    activeRequestRef.current = { requestId, controller };
    ignoreDeltasRef.current = false;
    setStreamError("");
    setWaitingPhraseIndex(0);
    setPlanState("connecting");
    setPendingTurn({
      id: `pending-${requestId}`,
      request_id: requestId,
      userContent: options.showUser === false ? "" : clean,
      content: "",
      activity: [],
      optimistic: true,
    });
    if (!options.keepComposer) setMessage("");
    try {
      await onChat(clean, requestId, {
        signal: controller.signal,
        onEvent: (event) => {
          if (activeRequestRef.current?.requestId === requestId) handleStreamEvent(event);
        },
        retry: options.retry,
      });
      if (activeRequestRef.current?.requestId === requestId) {
        setPendingTurn(null);
        setPlanState("idle");
        window.requestAnimationFrame(() => composerRef.current?.focus());
      }
    } catch (error) {
      if (error.name !== "AbortError" && activeRequestRef.current?.requestId === requestId) {
        setPlanState("error");
        setStreamError(error.message);
      }
    } finally {
      if (activeRequestRef.current?.requestId === requestId) activeRequestRef.current = null;
    }
  }

  function stopGeneration() {
    // Stops visible output immediately and asks the provider stream to close cooperatively.
    const requestId = activeRequestRef.current?.requestId;
    if (!requestId) return;
    ignoreDeltasRef.current = true;
    setPlanState("stopped");
    setPendingTurn((current) => ({ ...(current || {}), stopped: true }));
    onStopChat(requestId).catch((error) => setStreamError(error.message));
    composerRef.current?.focus();
  }

  function retryTurn(turn) {
    // Reuses the persisted request id so the backend updates, rather than duplicates, the pair.
    const original = conversationItems.find((item) => item.role === "user" && item.request_id === turn.request_id);
    if (original) sendPlanMessage(original.content, { requestId: turn.request_id, retry: true, showUser: false });
  }

  function jumpToLatest() {
    if (!chatLogRef.current) return;
    setAutoScroll(true);
    chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
  }

  const modelIdentity = [...conversationItems].reverse().find((turn) => turn.role === "assistant")?.extracted_updates?.model_identity || "Project model";

  return (
    <div className={`panel brief-workspace conversational-brief-workspace${compact ? " compact" : ""}`}>
      <header className="brief-editor-header">
        <div>
          <span className="workspace-eyebrow">Layer 0 strategy workspace</span>
          <h3>{mode === "AI Chat" ? "Refine the product with Strata" : "Edit the saved brief directly"}</h3>
          <p className="muted">The conversation can propose changes. Only you can apply them to the saved brief.</p>
        </div>
        <div className="brief-editor-header-side">
          <span className={`status-pill ${brief?.status || "draft"}`}>{displayStatusLabel(brief?.status)}</span>
          <div className="segmented brief-mode-toggle" aria-label="Layer 0 editing mode">
            {MODE_OPTIONS.map((item) => (
              <button key={item.id} type="button" className={mode === item.id ? "active" : ""} onClick={() => setMode(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {mode === "AI Chat" ? (
        <section className="layer0-conversation" aria-label="Layer 0 AI conversation">
          <div
            ref={chatLogRef}
            className="layer0-message-thread"
            role="log"
            aria-live="polite"
            aria-relevant="additions text"
            onScroll={(event) => setAutoScroll(isNearConversationBottom(event.currentTarget))}
          >
            {!conversationStarted ? (
              <div className="layer0-empty-state">
                <div className="layer0-empty-mark" aria-hidden="true">S</div>
                <h4>Shape the brief through conversation</h4>
                <p>Tell me about the product you are building, the problem it solves, or the part of the idea that still feels unclear. I&apos;ll help shape it into the Layer 0 brief.</p>
                <div className="layer0-starter-row" aria-label="Conversation starters">
                  {STARTERS.map((starter) => <button key={starter} type="button" className="preset-chip" onClick={() => sendPlanMessage(starter)}>{starter}</button>)}
                </div>
              </div>
            ) : null}
            {conversationItems.map((turn) => (
              <ChatTurn key={turn.id} turn={turn} onProposalDecision={onProposalDecision} onRetry={retryTurn} />
            ))}
            {pendingTurn?.userContent ? (
              <ChatTurn turn={{ id: `${pendingTurn.id}-user`, role: "user", content: pendingTurn.userContent }} onProposalDecision={onProposalDecision} onRetry={retryTurn} />
            ) : null}
            {pendingTurn ? (
              <article className={`layer0-message assistant ${planState}`} aria-label="Assistant response in progress">
                <div className="layer0-message-meta"><strong>Strata</strong><span>Now</span></div>
                {pendingTurn.content ? <div className="layer0-message-content">{safeAssistantContent(pendingTurn.content)}</div> : null}
                {planState === "connecting" ? (
                  <div className="layer0-thinking-state" role="status"><span className="thinking-dot" />{LAYER0_WAITING_PHRASES[waitingPhraseIndex]}</div>
                ) : null}
                {pendingTurn.stopped ? <p className="message-footnote">Stopped by you. The partial response will remain in this project.</p> : null}
                <ActivitySummary steps={pendingTurn.activity} />
              </article>
            ) : null}
            {streamError ? (
              <div className="inline-conversation-error" role="alert">
                <strong>The response was interrupted.</strong>
                <span>{streamError}</span>
              </div>
            ) : null}
          </div>

          {!autoScroll ? <button type="button" className="jump-to-latest" onClick={jumpToLatest}>Jump to latest</button> : null}

          {guidance?.next_questions?.length && !isGenerating ? (
            <div className="layer0-quick-responses" aria-label="Suggested responses">
              {guidance.next_questions.slice(0, 3).map((question) => (
                <button key={question} type="button" className="preset-chip" onClick={() => sendPlanMessage(question)}>{question}</button>
              ))}
            </div>
          ) : null}

          <form
            className="layer0-composer"
            onSubmit={(event) => { event.preventDefault(); sendPlanMessage(message); }}
          >
            <textarea
              ref={composerRef}
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (!shouldSubmitComposer(event)) return;
                event.preventDefault();
                sendPlanMessage(message);
              }}
              rows={3}
              placeholder="Ask a question, add context, or challenge the current brief…"
              aria-label="Message Strata"
              disabled={false}
            />
            <div className="layer0-composer-footer">
              <span className="layer0-model-label">{modelIdentity} · Enter to send · Shift+Enter for a new line</span>
              {isGenerating ? (
                <button type="button" className="stop-generation-button" onClick={stopGeneration} aria-label="Stop generating">■ Stop</button>
              ) : (
                <button type="submit" disabled={!message.trim()} aria-label="Send message">Send</button>
              )}
            </div>
          </form>
        </section>
      ) : (
        <section className="brief-editor-section">
          <div className={`brief-editor-notice ${isDirty ? "warning" : "success"}`}>
            <strong>{isDirty ? "These edits are not saved yet." : "The form matches the saved brief."}</strong>
            <span>{isDirty ? "Save to update the canonical Layer 0 source of truth." : "Use the conversation when you want help challenging or refining it."}</span>
          </div>
          {brief?.status === "published" ? (
            <div className="brief-editor-notice warning">
              <strong>This Layer 0 brief is published.</strong>
              <span>Saving changes returns it to draft so downstream work can be reviewed before republishing.</span>
            </div>
          ) : null}
          <div className="brief-grid layer0-brief-form canonical-brief-form">
            {FORM_FIELDS.map((field) => (
              <label key={field.key} className={["product_idea", "problem"].includes(field.key) ? "brief-field-span" : ""}>
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
          <div className="brief-editor-footer">
            <button type="button" onClick={() => onSave(payload)} disabled={!isDirty}>Save brief</button>
          </div>
        </section>
      )}
    </div>
  );
}
