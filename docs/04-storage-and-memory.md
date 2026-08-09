# Storage And Memory

Strata keeps PostgreSQL as the production source of truth and uses bounded memory packets for model context.

## Production persistence

- PostgreSQL is selected with `STRATA_DB_BACKEND=postgres` and
  `STRATA_DATABASE_URL`. The native default `.env.example` points at
  `127.0.0.1:55433`; Docker Compose uses its internal `postgres:5432` service.
- `pgvector` stores semantic representations used by overlap checks and retrieval.
- Core project records include projects, lifecycle state, briefs, conversations,
  Layer 1 nodes, generations, research, platform jobs, telemetry, diagnostics,
  ownership settings, archives, and project memory.
- Platform workers claim queued jobs with one database compare-and-set transition,
  so separate API worker processes cannot dispatch the same job concurrently.
- Importing `strata.api` is storage-free. The explicit `serve_api` ASGI entrypoint
  constructs the application and initializes the configured database at startup.
- Layer 2 uses dedicated graph, provenance, coverage, review, rejection-memory, and competitor-evidence tables.
- Layer 3 uses dedicated card, relationship, open-decision, and review-action tables; readiness, optional competitive analysis, and provenance live on the card rather than in raw chat history.
- The project assistant persists conversations, messages, runs, specialist runs, documents, and action proposals.

SQLite is not the production runtime. It remains available for isolated tests,
disposable release QA runs, and one-time import or compatibility work with
older local data.

## Memory behavior

- Do not feed the entire generation history back into the model.
- Keep compressed coverage summaries, overlap clusters, uncovered areas, rejected ideas, and durable assistant summaries.
- Let the database store detailed history while prompts receive only the bounded state required for the current operation.
- Bound Layer 3 prompts to the current approved feature, parent pillar, approved siblings, relevant graph edges, compact brief context, and the current card during section reruns.

## Deduplication

- Use canonical families, semantic embeddings, aliases, and graph relationships to identify overlap.
- Use lexical matching as supporting evidence rather than the primary Layer 1 or Layer 2 decision.
- Mark possible duplicates rather than deleting them automatically.
- Allow the user to decide what should be kept, merged, linked, or cut.

## Performance behavior

- Prefer indexed and bounded reads over scanning full project history.
- Keep layer-specific memory scoped to the relevant entity or parent.
- Preserve user-owned status and priority unless the user explicitly changes them.
- Reuse stored research pages, chunks, findings, embeddings, and assistant documents where their source state is unchanged.
