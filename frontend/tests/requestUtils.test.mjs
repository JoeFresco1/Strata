import test from "node:test";
import assert from "node:assert/strict";
import { withExpectedStateToken, withRequestId } from "../src/requestUtils.js";

test("withRequestId adds a generated request ID without mutating the payload", () => {
  const payload = { action: "approve" };
  const result = withRequestId(payload);

  assert.notEqual(result, payload);
  assert.deepEqual(result, { action: "approve", request_id: result.request_id });
  assert.match(result.request_id, /^[0-9a-f-]{36}$/i);
});

test("withRequestId preserves an explicit request ID", () => {
  assert.deepEqual(withRequestId({ value: 1 }, "request-123"), {
    value: 1,
    request_id: "request-123",
  });
});

test("withExpectedStateToken adds concurrency metadata and preserves payload fields", () => {
  assert.deepEqual(withExpectedStateToken({ action: "publish" }, "state-123", "request-123"), {
    action: "publish",
    expected_state_token: "state-123",
    request_id: "request-123",
  });
});
