import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  isNearConversationBottom,
  parseLayer0EventBuffer,
  safeAssistantContent,
  shouldSubmitComposer,
} from "../src/layer0Conversation.js";

test("stream events remain incremental across split network chunks", () => {
  const first = parseLayer0EventBuffer('data: {"type":"delta","content":"Hel');
  assert.deepEqual(first.events, []);
  const second = parseLayer0EventBuffer(`${first.remainder}lo"}\n\ndata: {"type":"complete"}\n\n`);
  assert.deepEqual(second.events, [
    { type: "delta", content: "Hello" },
    { type: "complete" },
  ]);
});

test("primary assistant copy removes thought and channel markup", () => {
  assert.equal(safeAssistantContent("<think>private</think>Public"), "Public");
  assert.equal(
    safeAssistantContent("<|channel|>analysis private<|channel|>final<|message|>Public"),
    "Public",
  );
});

test("auto-scroll follows only while the reader remains near the bottom", () => {
  assert.equal(isNearConversationBottom({ scrollHeight: 1000, scrollTop: 850, clientHeight: 100 }), true);
  assert.equal(isNearConversationBottom({ scrollHeight: 1000, scrollTop: 300, clientHeight: 100 }), false);
});

test("Enter sends while Shift+Enter preserves a multiline composer", () => {
  assert.equal(shouldSubmitComposer({ key: "Enter", shiftKey: false, nativeEvent: { isComposing: false } }), true);
  assert.equal(shouldSubmitComposer({ key: "Enter", shiftKey: true, nativeEvent: { isComposing: false } }), false);
});

test("Layer 0 source removes redundant controls and includes conversation safeguards", async () => {
  const source = await readFile(new URL("../src/BriefWorkspace.jsx", import.meta.url), "utf8");
  for (const removed of ["Brief coverage", "Review weak spots", "Ask next question", "Improve clarity", "Generate missing brief fields"]) {
    assert.equal(source.includes(removed), false, `${removed} should be removed`);
  }
  for (const required of ["Jump to latest", "Stop", "Show activity", "Proposed brief update", "Shift+Enter", "Retry response"]) {
    assert.equal(source.includes(required), true, `${required} should remain represented`);
  }
});
