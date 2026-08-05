import { API_BASE, apiErrorMessage } from "./apiClient.js";

export const LAYER0_WAITING_PHRASES = [
  "Turning the idea over…",
  "Looking for the weak spots…",
  "Connecting the product pieces…",
  "Checking what is still missing…",
  "Separating the real product from the feature pile…",
  "Making the brief less vague…",
  "Following the idea to its edges…",
];

// Splits complete server-sent events from the still-incomplete network buffer.
export function parseLayer0EventBuffer(buffer) {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const remainder = blocks.pop() || "";
  const events = blocks.flatMap((block) => {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return [];
    try {
      return [JSON.parse(data)];
    } catch {
      return [];
    }
  });
  return { events, remainder };
}

// Streams one real provider response and forwards every typed transport event.
export async function streamLayer0Conversation({ projectId, body, signal, onEvent }) {
  const response = await fetch(`${API_BASE}/projects/${projectId}/brief/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(apiErrorMessage(payload.detail, response.status));
    error.detailPayload = payload.detail;
    throw error;
  }
  if (!response.body) throw new Error("The model response stream was unavailable.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const parsed = parseLayer0EventBuffer(buffer);
    buffer = parsed.remainder;
    parsed.events.forEach(onEvent);
    if (done) break;
  }
}

// Keeps automatic scrolling opt-in once the reader intentionally moves upward.
export function isNearConversationBottom(element, threshold = 96) {
  if (!element) return true;
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
}

// Prevents raw local-model thought/channel markup from leaking into primary copy.
export function safeAssistantContent(value) {
  return String(value || "")
    .replace(/<think>[\s\S]*?<\/think>/gi, "")
    .replace(/<\|?channel\|?>\s*(analysis|thought)[\s\S]*?<\|?channel\|?>\s*final(?:<\|?message\|?>)?/gi, "")
    .replace(/<\|?(channel|message|start|end)\|?>/gi, "")
    .trim();
}

// Implements the familiar Enter-to-send and Shift+Enter-to-newline contract.
export function shouldSubmitComposer(event) {
  return event.key === "Enter" && !event.shiftKey && !event.nativeEvent?.isComposing;
}
