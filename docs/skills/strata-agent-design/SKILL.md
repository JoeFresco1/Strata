# Strata Agent Design Skill

## When To Use

Use this skill when working on any of the following in Strata:

- agent profiles
- orchestration rules
- system prompts
- reviewer or critic passes
- model sequencing
- generation workflows
- tool selection
- local memory and retrieval strategy
- command design for the localhost app
- future subagent planning

Use it when the question is not just "write code," but "how should Strata think, coordinate, and move through layered generation work?"

## Project Intent

Strata is not a general chatbot. It is a local-first product discovery and feature-architecture platform with human-in-the-loop pruning.

The core interaction pattern is:

1. broaden or decompose
2. dedupe
3. summarize
4. review with a human
5. continue deeper only on approved nodes

The system should prefer structured, bounded, auditable generation over open-ended autonomy.

## Current Runtime Assumptions

- local `llama.cpp` inference over HTTP
- local GGUF models
- Python service layer in `strata/`
- localhost `FastAPI + React` app
- PostgreSQL and pgvector as the production persistence layer
- centralized prompt templates in `prompts.json`

Do not design workflows that assume cloud APIs, hosted vector databases, or uncontrolled external services unless the user explicitly asks for that direction.

## Core Design Principles

### 1. Human Checkpoints Are Mandatory

Strata should widen or deepen a layer aggressively, but only inside bounded passes.

The human should always be able to:

- keep
- cut
- rename
- prioritize
- merge
- decide what expands next

### 2. Prefer Multi-Pass Roles Over Autonomous Agents

For this project, role-based passes are usually better than free-running agents.

Preferred pattern:

- generator
- normalizer
- assessor
- deduper
- critic
- summarizer
- prioritizer

These passes may use the same model or different models, but each pass should have a narrow job.

### 3. Breadth Before Depth

Layer 1 should optimize for broad pillar discovery before deep implementation detail.

Layer 2 should optimize for graph-native feature discovery within approved pillars, including scope, ownership, overlap, relationships, shared concerns, and rejection memory.

Layer 3 should optimize for clear product-level capability definition while minimizing overlap with shared capabilities already found elsewhere and excluding implementation specifications.

### 4. Anti-Rediscovery Matters

The system should avoid re-inventing the same concept under different names.

Always consider:

- rejected ideas
- canonical families
- cross-pillar overlap
- shared components
- prior critic summaries

### 5. Local Memory Beats Full Replay

Do not keep stuffing full prior generations back into the context window.

Prefer:

- compressed summaries
- canonical family memory
- overlap clusters
- approved directions
- rejected directions
- targeted retrieval for the active layer

## Recommended Agent Shape For Strata

If defining an agent profile for this project, bias toward this structure:

### Identity

- senior product-architecture assistant
- strong at decomposition
- strict about duplication
- local-first and auditable

### System Prompt Goals

The system prompt should emphasize:

- structured JSON output
- non-overlapping concept discovery
- recall first, then pruning
- resistance to vague relabeling
- preference for reusable shared capabilities
- explicit stop conditions

### Memory File Goals

The memory file or `AGENTS.md` companion should capture:

- project architecture
- current layer behavior
- model/runtime constraints
- prompt centralization rules
- todo logging rules
- refactor triggers
- documentation expectations

## Recommended Workflow Patterns

### Pattern 1: Layer Broadening Loop

Use for Layer 1 and, with narrower scope, Layer 2.

1. generate a batch
2. normalize the batch
3. assess quality and true-layer fit
4. dedupe against canonical memory
5. save accepted nodes
6. quarantine weak or off-layer candidates
7. run critic and summarizer
8. decide whether to continue

### Pattern 2: Downward Expansion Loop

Use for Layer 2 and Layer 3 after approval gates.

1. retrieve parent context
2. retrieve shared-capability memory
3. generate child items
4. check cross-branch overlap
5. save accepted items
6. summarize new coverage

### Pattern 3: Shared Capability Detection

Use when multiple pillars start producing the same feature family.

1. detect overlap by title, description, and canonical concept
2. ask whether this is really one reusable component
3. prefer one canonical capability plus branch-specific dependencies

## Recommended Commands For A Strata Agent

If implementing command-style workflows later, these are good candidates:

- `/broaden-layer1`
- `/review-layer1-overlap`
- `/expand-layer2`
- `/generate-layer3-specs`
- `/summarize-project-memory`
- `/find-shared-components`
- `/export-project`

Each command should map to a bounded workflow with clear inputs, outputs, and persistence points.

## Guidance On Subagents

Subagents may be useful later, but they should be narrow and cheap.

Good future subagents:

- `pillar-critic`
- `spec-reviewer`
- `duplication-auditor`
- `risk-reviewer`
- `ux-flow-reviewer`

Bad pattern:

- one autonomous manager agent that recursively spawns more agents without hard limits

## Retrieval And RAG Guidance

Do not treat Strata as a classic document-RAG product by default.

What it really needs is project-memory retrieval:

- what already exists
- what was rejected
- what overlaps
- what should be reused
- what coverage gaps remain

If retrieval is added, prioritize:

- sibling retrieval
- cross-pillar retrieval
- rejection memory
- shared component retrieval
- critic summary retrieval

## Persistence Expectations

Every meaningful generation step should leave artifacts behind:

- nodes
- generation logs
- coverage memory
- quarantine memory
- exportable tree state

The system should be restart-safe and review-safe.

## Readability And Maintenance Rules

When using this skill to shape code:

- keep orchestration readable
- comment all new functions
- prefer small helpers over giant controller functions
- centralize prompts outside runtime logic
- only refactor proactively when the project refactor triggers are met

Respect the project rules in:

- `AGENTS.md`
- `docs/TODO_LOG.md`

## What Good Looks Like

A good Strata agent workflow should feel like:

- ambitious in exploration
- conservative in persistence
- explicit about why it continued or stopped
- easy for a human to audit
- easy for a human to redirect
- resistant to duplicate rediscovery
- fast to rerun locally

## What To Avoid

- endless recursive generation
- hidden state the user cannot inspect
- giant prompts with raw replay of everything
- duplicated logic across layers
- agent chains with unclear ownership
- expensive orchestration that does not improve coverage quality

## Project-Specific Default Recommendation

For Strata, the default orchestration stance should be:

- bounded recursive generation
- checkpointed persistence
- compressed memory
- explicit coverage review
- human approval gates
- localhost-first execution

That should remain the default unless the user intentionally asks for a more autonomous architecture.
