# Strata Production Architecture

## Supported product boundary

The current production product covers Layer 0 through Layer 3.

- Layer 0 creates and publishes the canonical product brief.
- Layer 1 discovers and reviews major product pillars.
- Layer 2 creates and reviews a provenance-aware feature graph.
- Layer 3 creates and reviews product-level Capability Design Cards for approved Layer 2 features.

## Runtime topology

The supported localhost stack consists of:

1. React and Vite on `127.0.0.1:5173`
2. FastAPI on `127.0.0.1:8000`
3. PostgreSQL with pgvector on `127.0.0.1:55433`
4. An OpenAI-compatible model endpoint, normally managed `llama.cpp` on `127.0.0.1:8080`

`start_specforge.ps1` is the canonical full-stack launcher. `stop_specforge.ps1` stops the managed frontend, API, model server, and local PostgreSQL processes.

## Application boundaries

### React client

The frontend owns user interaction and transient view state. It does not own canonical project state.

Primary surfaces:

- project library
- Layer 0 brief workspace
- living Map/Table workspace spanning Layer 0 through Layer 2
- Capability Design workspace for Layer 3 generation, section editing, relationships, decisions, pressure testing, review, and export
- contextual entity inspector for editing, review, research, and downward generation
- project settings, competitive intelligence, exports, and diagnostics
- unified project assistant drawer

The workspace persists its selected entity, view mode, branch/table scope, and filters per project. Graph-native Layer 2 features are projected beneath their owner pillars for navigation, while cross-pillar relationships remain secondary graph edges.

### FastAPI service

FastAPI is the production application boundary. It validates requests, coordinates service calls, returns project snapshots, and exposes generation, research, review, assistant, settings, and export operations.

Business logic belongs in focused services and database adapters rather than React components or endpoint handlers.

### Model execution

Model profiles use OpenAI-compatible endpoints. Profiles may point to managed local GGUF models or remote APIs.

Execution intent is explicit:

- `local_first`
- `api_first`
- `blended`

Routing is resolved by domain for Layer 0, generation, research, and assistant work. Profile availability can cause a fallback, so provider preference is not an absolute availability guarantee.

### PostgreSQL and pgvector

PostgreSQL is the production source of truth. It stores canonical project state, generated artifacts, research, Layer 2 graph state, assistant state, settings, and provenance.

pgvector supports semantic overlap and retrieval. SQLite is restricted to tests and one-time legacy import compatibility.

## Canonical data flows

### Layer 0

1. The user plans conversationally or edits the form.
2. Both modes update one canonical brief.
3. Publishing freezes the brief as the Layer 1 input and queues research.

### Layer 1

1. Bounded model passes generate pillar candidates.
2. Normalization and assessment enforce Layer 1 granularity.
3. Canonical families, embeddings, and prior memory reduce rediscovery.
4. Human review decides which pillars can descend.

### Layer 2

1. Approved pillars receive scope contracts and coverage families.
2. Bounded lens passes create raw feature candidates.
3. Integrity and graph critics classify scope, granularity, duplication, ownership, and relationships.
4. Canonical features and provenance are persisted in graph-native tables.
5. Human review controls merges, cuts, approvals, and relationship changes.
6. Competitor research attaches cited evidence to active features.

### Layer 3

1. Only approved Layer 2 features are eligible.
2. Generation receives compact Layer 0 context, the parent pillar, approved siblings, and relevant graph edges.
3. The card defines purpose, archetype, variants, options, behaviors, product-level constraints, lifecycle states, relationships, dependencies, conflicts, edge cases, risks, and open decisions.
4. A separate pressure-test pass identifies ambiguity, overreach, product risk, missing decisions, downstream blockers, and implementation leakage.
5. Cards, relationships, decisions, readiness scores, provenance, and review actions are persisted independently of chat history.
6. Human reviewers can edit, selectively regenerate, resolve decisions, approve, reject, and export cards.
7. The downstream JSON manifest includes approved cards and complete Layer 0/1/2 lineage. Layer 3 never generates target-product APIs, database schemas, components, test cases, wireframes, user stories, architecture diagrams, or coding tasks.

### Project assistant

1. Conversations and messages are durable.
2. The assistant performs bounded, allowlisted project reads.
3. Optional specialists analyze retrieved evidence.
4. Synthesis returns cited answers.
5. Mutations remain inert action proposals until the user confirms them.

## Retired architecture

The following are not supported production paths:

- Streamlit UI and its standalone application entrypoint
- tree-mode Layer 2 subfeature generation
- SQLite as the primary application database
- separate layer-specific assistants
- raw model output as canonical state without validation and persistence

Historical records may still contain older node shapes. Compatibility with stored data is separate from the supported architecture and should not be used as a reason to create new legacy records.
