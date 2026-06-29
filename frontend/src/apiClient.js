const API_BASE = (
  import.meta.env?.VITE_API_BASE
  || (typeof window === "undefined" ? "http://127.0.0.1:8000/api" : "/api")
).replace(/\/$/, "");
const MAX_CACHE_ENTRIES = 48;
const MAX_STALE_RETRIES = 3;
const responseCache = new Map();
const inFlightGets = new Map();
const inFlightMutations = new Map();
const activityListeners = new Set();
let pendingMutationCount = 0;

// Converts FastAPI string, object, and validation-list details into readable UI text.
export function apiErrorMessage(detail, status) {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => item?.msg || item?.message || "")
      .filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.message === "string" && detail.message.trim()) return detail.message;
    try {
      return JSON.stringify(detail);
    } catch {
      // Fall through to the status-based message for non-serializable payloads.
    }
  }
  return `Request failed: ${status}`;
}

// Notifies the shell when visible write requests start or finish.
function updateMutationActivity(delta) {
  pendingMutationCount = Math.max(0, pendingMutationCount + delta);
  activityListeners.forEach((listener) => listener(pendingMutationCount));
}

// Subscribes a UI surface to the shared mutation activity count.
export function subscribeApiActivity(listener) {
  activityListeners.add(listener);
  listener(pendingMutationCount);
  return () => activityListeners.delete(listener);
}

// Assigns short cache windows to stable reads while keeping active project data fresh.
function cacheTtlForPath(path) {
  if (path === "/config") return 60_000;
  if (path === "/projects") return 5_000;
  if (/^\/projects\/[^/]+$/.test(path)) return 1_000;
  return 0;
}

// Returns the cache prefixes affected by a mutation without flushing unrelated app state.
function invalidationPrefixesForPath(path) {
  if (!path) return [];
  if (path.startsWith("/config")) return ["=/config"];
  if (path === "/projects") return ["=/projects"];
  const projectMatch = path.match(/^\/projects\/([^/]+)/);
  if (projectMatch) {
    const projectPath = `/projects/${projectMatch[1]}`;
    const prefixes = ["=/projects", `=${projectPath}`];
    if (path.startsWith(`${projectPath}/assistant/`)) prefixes.push(`${projectPath}/assistant`);
    return prefixes;
  }
  if (path.startsWith("/nodes/")) return ["=/projects", "/projects/*"];
  return [];
}

// Reports whether a cached or in-flight GET belongs to an invalidated prefix.
function matchesPrefix(path, prefix) {
  if (prefix.startsWith("=")) return path === prefix.slice(1);
  if (prefix.endsWith("/*")) {
    const base = prefix.slice(0, -2);
    return path.startsWith(`${base}/`);
  }
  return path === prefix || path.startsWith(`${prefix}/`);
}

// Removes expired entries and trims least-recently-used values to the fixed memory budget.
function pruneResponseCache(now = Date.now()) {
  for (const [path, entry] of responseCache.entries()) {
    if (entry.expiresAt <= now) responseCache.delete(path);
  }
  if (responseCache.size <= MAX_CACHE_ENTRIES) return;
  const oldest = [...responseCache.entries()]
    .sort((left, right) => left[1].lastAccessedAt - right[1].lastAccessedAt)
    .slice(0, responseCache.size - MAX_CACHE_ENTRIES);
  oldest.forEach(([path]) => responseCache.delete(path));
}

// Reads one live cache entry and refreshes its LRU timestamp.
function cachedResponse(path, now) {
  const entry = responseCache.get(path);
  if (!entry) return undefined;
  if (entry.expiresAt <= now) {
    responseCache.delete(path);
    return undefined;
  }
  entry.lastAccessedAt = now;
  return entry.value;
}

// Parses one API response while preserving readable FastAPI error details.
async function responsePayload(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(apiErrorMessage(body.detail, response.status));
    error.detailPayload = body.detail;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

// Builds a stable enough identity for suppressing duplicate writes already in progress.
function mutationKey(method, path, body) {
  return `${method}:${path}:${typeof body === "string" ? body : JSON.stringify(body || null)}`;
}

// Removes cached reads and marks matching in-flight reads stale so they transparently retry.
export function invalidateApiCache(path = "", extraPrefixes = []) {
  const prefixes = path
    ? [...invalidationPrefixesForPath(path), ...extraPrefixes]
    : [];
  if (!prefixes.length) {
    responseCache.clear();
    inFlightGets.forEach((entry) => {
      entry.invalidated = true;
    });
    inFlightGets.clear();
    return;
  }
  const uniquePrefixes = [...new Set(prefixes)];
  for (const key of responseCache.keys()) {
    if (uniquePrefixes.some((prefix) => matchesPrefix(key, prefix))) responseCache.delete(key);
  }
  for (const [key, entry] of inFlightGets.entries()) {
    if (!uniquePrefixes.some((prefix) => matchesPrefix(key, prefix))) continue;
    entry.invalidated = true;
    if (inFlightGets.get(key) === entry) inFlightGets.delete(key);
  }
}

// Starts one GET and retries once if a completed mutation invalidated it while it was in flight.
function startGet(path, fetchOptions, cacheTtl, staleRetries) {
  const entry = { invalidated: false, promise: null };
  entry.promise = fetch(`${API_BASE}${path}`, {
    ...fetchOptions,
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(fetchOptions.headers || {}),
    },
  })
    .then(responsePayload)
    .then((payload) => {
      if (entry.invalidated && staleRetries < MAX_STALE_RETRIES) {
        return apiFetch(path, {
          ...fetchOptions,
          method: "GET",
          force: true,
          staleRetries: staleRetries + 1,
          cacheTtl,
        });
      }
      if (entry.invalidated) {
        throw new Error("Data changed repeatedly while loading. Retry the request.");
      }
      if (!entry.invalidated && cacheTtl > 0) {
        const now = Date.now();
        responseCache.set(path, {
          value: payload,
          expiresAt: now + cacheTtl,
          lastAccessedAt: now,
        });
        pruneResponseCache(now);
      }
      return payload;
    })
    .finally(() => {
      if (inFlightGets.get(path) === entry) inFlightGets.delete(path);
    });
  inFlightGets.set(path, entry);
  return entry.promise;
}

// Fetches JSON with bounded caching, in-flight reuse, targeted invalidation, and stale-read protection.
export async function apiFetch(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const cacheTtl = options.cacheTtl ?? cacheTtlForPath(path);
  const force = Boolean(options.force);
  const silent = Boolean(options.silent);
  const staleRetries = Number(options.staleRetries || 0);
  const invalidate = Array.isArray(options.invalidate) ? options.invalidate : [];
  const {
    cacheTtl: _cacheTtl,
    force: _force,
    silent: _silent,
    staleRetries: _staleRetries,
    invalidate: _invalidate,
    ...fetchOptions
  } = options;

  if (method === "GET") {
    const now = Date.now();
    pruneResponseCache(now);
    if (!force) {
      const cached = cachedResponse(path, now);
      if (cached !== undefined) return cached;
    }
    const activeRequest = inFlightGets.get(path);
    if (activeRequest) return activeRequest.promise;
    return startGet(path, fetchOptions, cacheTtl, staleRetries);
  }

  const key = mutationKey(method, path, fetchOptions.body);
  if (inFlightMutations.has(key)) return inFlightMutations.get(key);
  if (!silent) updateMutationActivity(1);
  const request = fetch(`${API_BASE}${path}`, {
    ...fetchOptions,
    method,
    headers: {
      "Content-Type": "application/json",
      ...(fetchOptions.headers || {}),
    },
  })
    .then(responsePayload)
    .then((payload) => {
      invalidateApiCache(path, invalidate);
      return payload;
    })
    .finally(() => {
      inFlightMutations.delete(key);
      if (!silent) updateMutationActivity(-1);
    });
  inFlightMutations.set(key, request);
  return request;
}

// Exposes small diagnostics for deterministic tests and future cache observability.
export function apiCacheStats() {
  pruneResponseCache();
  return {
    cachedResponses: responseCache.size,
    inFlightGets: inFlightGets.size,
    inFlightMutations: inFlightMutations.size,
    pendingMutations: pendingMutationCount,
    maxEntries: MAX_CACHE_ENTRIES,
  };
}

// Clears module state between deterministic request-policy tests.
export function resetApiClientState() {
  responseCache.clear();
  inFlightGets.clear();
  inFlightMutations.clear();
  pendingMutationCount = 0;
}

export { API_BASE };
