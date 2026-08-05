// Adds the request metadata required by canonical mutation endpoints.
export function withRequestId(payload = {}, requestId = crypto.randomUUID()) {
  return { ...payload, request_id: requestId };
}

// Adds an optimistic-concurrency token while preserving the caller's request ID.
export function withExpectedStateToken(payload = {}, expectedStateToken, requestId) {
  return withRequestId({ ...payload, expected_state_token: expectedStateToken }, requestId);
}
