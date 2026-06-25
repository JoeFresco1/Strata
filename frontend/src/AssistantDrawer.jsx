import { useEffect, useRef, useState } from "react";

const SCOPES = ["overall", "layer0", "layer1", "layer2", "layer3"];
const EXECUTION_INTENT_OPTIONS = [
  { value: "", label: "Project default" },
  { value: "local_first", label: "Local-first" },
  { value: "api_first", label: "API-first" },
  { value: "blended", label: "Blended" },
];
const STARTER_PROMPTS = [
  "What should I work on next?",
  "Find the biggest gap in this branch.",
  "Summarize the current product direction.",
];

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
}

function actionForMessage(actions, messageId) {
  return actions.filter((action) => action.message_id === messageId);
}

export default function AssistantDrawer({ open, projectId, activeScope, focus = {}, apiFetch, onClose, onNavigate }) {
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState("");
  const [thread, setThread] = useState({ messages: [], actions: [] });
  const [scope, setScope] = useState(activeScope);
  const [references, setReferences] = useState([]);
  const [executionIntentOverride, setExecutionIntentOverride] = useState("");
  const [thinking, setThinking] = useState(false);
  const [deepMode, setDeepMode] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [threadLoading, setThreadLoading] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);
  const hasPendingMessages = thread.messages.some((message) => ["queued", "running"].includes(message.status));

  useEffect(() => setScope(activeScope), [activeScope]);

  useEffect(() => {
    if (!open || !projectId) return;
    loadConversations();
  }, [open, projectId]);

  useEffect(() => {
    if (!open || !conversationId) return undefined;
    loadThread(conversationId);
  }, [open, conversationId]);

  useEffect(() => {
    if (!open || !conversationId || !hasPendingMessages) return undefined;
    let cancelled = false;
    let timer;
    async function pollThread() {
      if (document.visibilityState === "hidden") {
        timer = window.setTimeout(pollThread, 2500);
        return;
      }
      await loadThread(conversationId, true);
      if (!cancelled) timer = window.setTimeout(pollThread, 1800);
    }
    timer = window.setTimeout(pollThread, 1800);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, conversationId, hasPendingMessages]);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [thread.messages]);

  async function loadConversations() {
    try {
      const items = await apiFetch(`/projects/${projectId}/assistant/conversations`);
      setConversations(items);
      if (!conversationId && items.length) setConversationId(items[0].id);
    } catch (loadError) {
      setError(loadError.message);
    }
  }

  async function loadThread(id, quiet = false) {
    if (!quiet) setThreadLoading(true);
    try {
      const payload = await apiFetch(`/projects/${projectId}/assistant/conversations/${id}`, { force: true });
      setThread(payload);
      if (!quiet) setError("");
    } catch (loadError) {
      if (!quiet) setError(loadError.message);
    } finally {
      if (!quiet) setThreadLoading(false);
    }
  }

  async function createConversation() {
    setError("");
    try {
      const conversation = await apiFetch(`/projects/${projectId}/assistant/conversations`, {
        method: "POST",
        body: JSON.stringify({ title: "New conversation", home_scope: scope }),
      });
      setConversations((current) => [conversation, ...current]);
      setConversationId(conversation.id);
      setReferences([]);
    } catch (createError) {
      setError(createError.message);
    }
  }

  async function sendMessage(event) {
    event.preventDefault();
    if (!draft.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      let targetId = conversationId;
      if (!targetId) {
        const conversation = await apiFetch(`/projects/${projectId}/assistant/conversations`, {
          method: "POST",
          body: JSON.stringify({ title: draft.trim().slice(0, 56), home_scope: scope }),
        });
        setConversations((current) => [conversation, ...current]);
        setConversationId(conversation.id);
        targetId = conversation.id;
      }
      await apiFetch(`/projects/${projectId}/assistant/conversations/${targetId}/messages`, {
        method: "POST",
        body: JSON.stringify({
          content: draft.trim(),
          request_id: requestId(),
          active_scope: scope,
          focus: { ...focus, active_scope: activeScope },
          reference_conversation_ids: references,
          execution_intent_override: executionIntentOverride || null,
          thinking_enabled: thinking,
          deep_mode: deepMode,
        }),
      });
      setDraft("");
      await loadThread(targetId);
    } catch (sendError) {
      setError(sendError.message);
    } finally {
      setBusy(false);
    }
  }

  async function decideAction(actionId, decision) {
    try {
      await apiFetch(`/projects/${projectId}/assistant/actions/${actionId}`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      await loadThread(conversationId);
    } catch (actionError) {
      setError(actionError.message);
    }
  }

  async function retryMessage(messageId) {
    try {
      await apiFetch(`/projects/${projectId}/assistant/messages/${messageId}/retry`, { method: "POST" });
      await loadThread(conversationId);
    } catch (retryError) {
      setError(retryError.message);
    }
  }

  function toggleReference(id) {
    setReferences((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  if (!open) return null;

  return (
    <aside className="assistant-drawer" aria-label="Strata project assistant">
      <header className="assistant-header">
        <div>
          <strong>Project Assistant</strong>
          <span>{scope === "overall" ? "All layers" : scope.replace("layer", "Layer ")}</span>
        </div>
        <button type="button" className="icon-button" aria-label="Close assistant" title="Close assistant" onClick={onClose}>x</button>
      </header>

      <div className="assistant-thread-controls">
        <select value={conversationId} onChange={(event) => setConversationId(event.target.value)} aria-label="Conversation">
          <option value="">New conversation</option>
          {conversations.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
        </select>
        <button type="button" className="icon-button" title="New conversation" aria-label="New conversation" onClick={createConversation}>+</button>
      </div>

      <div className="assistant-options">
        <details className="assistant-advanced-options">
          <summary>Advanced</summary>
          <label>
            Scope
            <select value={scope} onChange={(event) => setScope(event.target.value)}>
              {SCOPES.map((item) => <option key={item} value={item}>{item === "overall" ? "Overall" : item.replace("layer", "Layer ")}</option>)}
            </select>
          </label>
          <label>
            Execution
            <select value={executionIntentOverride} onChange={(event) => setExecutionIntentOverride(event.target.value)}>
              {EXECUTION_INTENT_OPTIONS.map((item) => <option key={item.label} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label className="toggle-label"><input type="checkbox" checked={thinking} onChange={(event) => setThinking(event.target.checked)} /> Thinking</label>
          <label className="toggle-label"><input type="checkbox" checked={deepMode} onChange={(event) => setDeepMode(event.target.checked)} /> Deep</label>
        </details>
        {conversations.length > 1 ? (
          <details className="assistant-references">
            <summary>Reference other conversations ({references.length})</summary>
            {conversations.filter((item) => item.id !== conversationId).map((item) => (
              <label key={item.id}><input type="checkbox" checked={references.includes(item.id)} onChange={() => toggleReference(item.id)} /> {item.title}</label>
            ))}
          </details>
        ) : null}
      </div>

      <div className="assistant-messages" aria-live="polite">
        {threadLoading ? <div className="assistant-loading"><div className="loading-spinner" /><span>Loading conversation...</span></div> : null}
        {!thread.messages.length ? (
          <div className="assistant-empty">
            <p>Ask about the current layer, compare decisions, find conflicts, or preview an action.</p>
            <div className="assistant-starter-prompts">
              {STARTER_PROMPTS.map((prompt) => (
                <button key={prompt} type="button" className="secondary-button" onClick={() => setDraft(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {thread.messages.map((message) => (
          <article key={message.id} className={`assistant-message ${message.role}`}>
            <div className="assistant-message-meta"><span>{message.role === "user" ? "You" : "Strata"}</span><span>{message.status}</span></div>
            {message.run?.execution_intent ? (
              <div className="assistant-message-meta">
                <span>{message.run.execution_intent}</span>
                <span>{message.run.runtime_kind}</span>
              </div>
            ) : null}
            {message.content ? <p>{message.content}</p> : <p className="muted">{message.status === "failed" ? message.error : "Working through project context..."}</p>}
            {message.citations?.length ? (
              <div className="assistant-citations">
                {message.citations.map((citation) => (
                  <button key={`${message.id}-${citation.source_id}`} type="button" onClick={() => onNavigate(citation.layer, citation)}>{citation.label}</button>
                ))}
              </div>
            ) : null}
            {actionForMessage(thread.actions || [], message.id).map((action) => (
              <div className="assistant-action" key={action.id}>
                <strong>{action.label}</strong>
                <span>{action.status}</span>
                {action.status === "pending" ? <div><button type="button" onClick={() => decideAction(action.id, "apply")}>Apply</button><button type="button" className="ghost-button" onClick={() => decideAction(action.id, "reject")}>Reject</button></div> : null}
              </div>
            ))}
            {message.status === "failed" ? <button type="button" onClick={() => retryMessage(message.id)}>Retry</button> : null}
          </article>
        ))}
        <div ref={endRef} />
      </div>

      {error ? <div className="assistant-error">{error}</div> : null}
      <form className="assistant-composer" onSubmit={sendMessage}>
        <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Ask Strata about this project..." rows={3} />
        <button type="submit" disabled={busy || !draft.trim()}>{busy ? "Queuing..." : "Send"}</button>
      </form>
    </aside>
  );
}
