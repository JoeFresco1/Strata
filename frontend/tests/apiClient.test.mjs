import assert from "node:assert/strict";
import test from "node:test";

import {
  apiCacheStats,
  apiFetch,
  resetApiClientState,
} from "../src/apiClient.js";

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test.beforeEach(() => {
  resetApiClientState();
});

test("deduplicates parallel GETs and reuses a live cached response", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    return jsonResponse({ calls });
  };

  const [left, right] = await Promise.all([
    apiFetch("/projects"),
    apiFetch("/projects"),
  ]);
  const cached = await apiFetch("/projects");

  assert.equal(calls, 1);
  assert.deepEqual(left, right);
  assert.deepEqual(cached, left);
});

test("force refresh bypasses cache but still joins an active network read", async () => {
  let calls = 0;
  let release;
  globalThis.fetch = async () => {
    calls += 1;
    await new Promise((resolve) => {
      release = resolve;
    });
    return jsonResponse({ calls });
  };

  const regular = apiFetch("/projects");
  while (!release) await new Promise((resolve) => setTimeout(resolve, 0));
  const forced = apiFetch("/projects", { force: true });
  release();

  assert.deepEqual(await regular, await forced);
  assert.equal(calls, 1);
});

test("invalidates only the affected project and project list", async () => {
  const calls = new Map();
  globalThis.fetch = async (url, options = {}) => {
    const key = `${options.method || "GET"}:${new URL(url).pathname}`;
    calls.set(key, (calls.get(key) || 0) + 1);
    return jsonResponse({ key, count: calls.get(key) });
  };

  await apiFetch("/config");
  await apiFetch("/projects");
  await apiFetch("/projects/alpha");
  await apiFetch("/projects/beta");
  await apiFetch("/projects/alpha/brief", { method: "PATCH", body: "{}" });
  await apiFetch("/config");
  await apiFetch("/projects");
  await apiFetch("/projects/alpha");
  await apiFetch("/projects/beta");

  assert.equal(calls.get("GET:/api/config"), 1);
  assert.equal(calls.get("GET:/api/projects"), 2);
  assert.equal(calls.get("GET:/api/projects/alpha"), 2);
  assert.equal(calls.get("GET:/api/projects/beta"), 1);
});

test("workspace writes do not invalidate unrelated assistant reads", async () => {
  const calls = new Map();
  globalThis.fetch = async (url, options = {}) => {
    const key = `${options.method || "GET"}:${new URL(url).pathname}`;
    calls.set(key, (calls.get(key) || 0) + 1);
    return jsonResponse({ key, count: calls.get(key) });
  };

  await apiFetch("/projects/alpha");
  await apiFetch("/projects/alpha/assistant/conversations", { cacheTtl: 60_000 });
  await apiFetch("/projects/alpha/workspace-state", { method: "PATCH", body: "{}" });
  await apiFetch("/projects/alpha");
  await apiFetch("/projects/alpha/assistant/conversations", { cacheTtl: 60_000 });

  assert.equal(calls.get("GET:/api/projects/alpha"), 2);
  assert.equal(calls.get("GET:/api/projects/alpha/assistant/conversations"), 1);
});

test("assistant writes invalidate assistant reads without flushing other projects", async () => {
  const calls = new Map();
  globalThis.fetch = async (url, options = {}) => {
    const key = `${options.method || "GET"}:${new URL(url).pathname}`;
    calls.set(key, (calls.get(key) || 0) + 1);
    return jsonResponse({ key, count: calls.get(key) });
  };

  await apiFetch("/projects/alpha/assistant/conversations", { cacheTtl: 60_000 });
  await apiFetch("/projects/beta");
  await apiFetch("/projects/alpha/assistant/conversations", { method: "POST", body: "{}" });
  await apiFetch("/projects/alpha/assistant/conversations", { cacheTtl: 60_000 });
  await apiFetch("/projects/beta");

  assert.equal(calls.get("GET:/api/projects/alpha/assistant/conversations"), 2);
  assert.equal(calls.get("GET:/api/projects/beta"), 1);
});

test("deduplicates identical mutations while preserving activity cleanup", async () => {
  let calls = 0;
  let release;
  globalThis.fetch = async () => {
    calls += 1;
    await new Promise((resolve) => {
      release = resolve;
    });
    return jsonResponse({ ok: true });
  };

  const left = apiFetch("/projects/alpha/brief", { method: "PATCH", body: "{\"name\":\"A\"}" });
  while (!release) await new Promise((resolve) => setTimeout(resolve, 0));
  const right = apiFetch("/projects/alpha/brief", { method: "PATCH", body: "{\"name\":\"A\"}" });
  release();

  assert.deepEqual(await left, await right);
  assert.equal(calls, 1);
  assert.equal(apiCacheStats().pendingMutations, 0);
});

test("does not invalidate successful cached reads when a mutation fails", async () => {
  let projectReads = 0;
  globalThis.fetch = async (url, options = {}) => {
    if ((options.method || "GET") === "GET") {
      projectReads += 1;
      return jsonResponse({ projectReads });
    }
    return jsonResponse({ detail: "Rejected" }, 400);
  };

  await apiFetch("/projects/alpha");
  await assert.rejects(
    apiFetch("/projects/alpha/brief", { method: "PATCH", body: "{}" }),
    /Rejected/,
  );
  await apiFetch("/projects/alpha");

  assert.equal(projectReads, 1);
});

test("retries an in-flight project read invalidated by a completed mutation", async () => {
  let projectReads = 0;
  let releaseFirstRead;
  globalThis.fetch = async (url, options = {}) => {
    const pathname = new URL(url).pathname;
    if ((options.method || "GET") === "GET" && pathname.endsWith("/projects/alpha")) {
      projectReads += 1;
      if (projectReads === 1) {
        await new Promise((resolve) => {
          releaseFirstRead = resolve;
        });
        return jsonResponse({ version: "stale" });
      }
      return jsonResponse({ version: "fresh" });
    }
    return jsonResponse({ ok: true });
  };

  const pendingRead = apiFetch("/projects/alpha");
  while (!releaseFirstRead) await new Promise((resolve) => setTimeout(resolve, 0));
  await apiFetch("/projects/alpha/brief", { method: "PATCH", body: "{}" });
  releaseFirstRead();

  assert.deepEqual(await pendingRead, { version: "fresh" });
  assert.equal(projectReads, 2);
});

test("caps cached responses with least-recently-used eviction", async () => {
  globalThis.fetch = async (url) => jsonResponse({ path: new URL(url).pathname });

  for (let index = 0; index < 70; index += 1) {
    await apiFetch(`/cache-entry-${index}`, { cacheTtl: 60_000 });
  }

  assert.equal(apiCacheStats().cachedResponses, 48);
});
