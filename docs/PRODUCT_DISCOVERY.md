# Product Discovery

Product Discovery is STRATA's durable product-landscape stage after a published
Layer 0 brief and before future Layer 1 context consumption. It determines how
the product should be examined. It does not generate pillars, normalize domains
into a taxonomy, start Layer 1, or require competitor research.

## Architecture

The implementation follows the existing application boundaries:

1. The Layer 0 publish command creates an immutable brief revision and performs
   no automatic discovery, research, or Layer 1 work.
2. An explicit `GenerateProductDiscovery` command queues the
   `product_discovery_generation` platform workflow.
3. `DiscoveryService` loads the exact current published brief, resolves the
   project's assigned runtime and discovery settings, renders the versioned
   prompt, validates typed output, restores mandatory baseline coverage,
   assigns stable nested IDs, runs a non-destructive practicality review, and
   persists a candidate revision.
4. Human edits and authority transitions use canonical commands and create
   replacement revisions. Published content is protected by database triggers.
5. Optional research uses the independent `competitor_research` workflow. Each
   completed competitor produces a durable checkpoint revision.
6. Deterministic compilers produce compact context records from approved
   revisions. They do not use a model to choose downstream inclusion.

No new autonomous-agent architecture was introduced. Discovery reuses the
existing command ledger, platform jobs, local-first runtime resolution,
research crawler, telemetry, artifact dependencies, and project snapshot.

## Data model and migration

Migration 8, `product_discovery_and_competitor_research`, adds:

- `product_discovery_heads` and `product_discovery_revisions`;
- `competitor_research_heads` and `competitor_research_revisions`;
- `discovery_context_projections`;
- published-content immutability triggers;
- project and app `discovery_settings`.

The typed schema is in `strata/discovery_models.py`. The canonical artifact
contains archetypes, reusable lenses, actors, lifecycle stages, deliberately
overlapping domains, enterprise obligations, cross-domain opportunities,
coverage risks, open questions, review findings, human-owned fields, model
fields, provenance, audit records, dependency metadata, and freshness.

Discovery and research each use `candidate`, `approved`, `published`,
`rejected`, and `superseded` authority states. Research is independently
versioned. Only approved or published project-local research can be attached.
Attachment or detachment creates a new discovery candidate and never changes a
published discovery revision.

Nested IDs are deterministic UUID5 values derived from project, item type, and
semantic label. Overlapping domains remain separate records. Human-added lenses
use caller-provided durable IDs.

## Commands and APIs

Product Discovery commands:

- `GenerateProductDiscovery`
- `ApproveProductDiscoveryRevision`
- `PublishProductDiscoveryRevision`
- `RejectProductDiscoveryRevision`
- `RestoreProductDiscoveryRevision`
- `UpdateDiscoveryHumanFields`
- `AddHumanDiscoveryLens`
- `ExcludeDiscoveryLens`
- `RequestDiscoveryRegeneration`
- `BuildLayer1DiscoveryContextProjection`

Competitor research commands:

- `StartCompetitorResearch`
- `CancelCompetitorResearch`
- `ApproveCompetitorResearchRevision`
- `RejectCompetitorResearchRevision`
- `AttachCompetitorResearchToDiscovery`
- `DetachCompetitorResearchFromDiscovery`
- `ExcludeCompetitorFinding`
- `IncludeCompetitorFinding`
- `AddCompetitor`
- `RemoveCompetitor`
- `RefreshCompetitorResearch`
- `RebuildCompetitiveContextProjection`

The focused REST surface is rooted at
`/api/projects/{project_id}/discovery`. It includes current candidate,
published revision, history, comparison, raw response, practicality review,
human fields, lens decisions, deterministic context, research history,
individual research revisions, source evidence, competitive comparison,
finding decisions, competitor scope changes, selective/stale refresh, job
cancellation, attachment, and projection rebuild routes. Mutations use command
idempotency keys and optimistic state tokens.

The canonical project snapshot exposes `product_discovery`, including current
and published discovery, retained histories, research, projections, state
tokens, and job state.

## Generation and review

Prompt `product_discovery_generation_v1`, version `1.0.0`, receives the exact
published brief, selected research mode, and baseline policy. Raw and parsed
model responses are retained. The response is schema-validated before
persistence.

The bounded practicality review is deterministic and low-variance. It retains
the original item and adds a durable finding with disposition, rationale,
reviewer type, confidence, human-review requirement, and evidence IDs. It flags
superficial analogies, preserves unusual but defensible ideas for human review,
and never silently deletes model output.

The baseline policy always evaluates:

- users and actors;
- workflow and decisions;
- administration and operations, including platform super-administration;
- lifecycle and failure modes;
- data and integrations;
- trust, governance, security, and privacy;
- commercial and enterprise readiness.

Models may add product-specific lenses and may narrow baseline relevance, but a
baseline lens cannot silently disappear.

## Research modes and checkpoints

`no_competitor_research` performs no external retrieval and does not create a
research revision. Discovery completes normally and records competitor
coverage as not evaluated.

`lightweight_competitor_scan` defaults to 4 competitors, 12 total sources, 120
seconds, and 3 sources per competitor. It prioritizes bounded first-party
product, documentation, help, API, release-note, security, and solution pages.

`deep_competitor_research` defaults to 8 competitors, 40 total sources, 600
seconds, and 8 sources per competitor. Secondary evidence is only used when
explicitly allowed. Every budget remains user-configurable and bounded.

The workflow resolves scope, collects sources, extracts evidence, infers
territories and pillars, builds advisory comparisons and derived lenses,
reviews evidence, and persists after each competitor. Failure for one
competitor records a failed profile and unresolved question while continuing
with the rest. Time or source exhaustion preserves completed profiles and
marks the revision partial. Cancellation at a checkpoint preserves the latest
checkpoint. Missing evidence yields a skipped or unresolved competitor, never
a fabricated finding.

Prompt `competitor_evidence_extraction_v1`, version `1.0.0`, structures observed
claims. `competitor_pillar_inference_v1`, version `1.0.0`, infers evidence-bound
territories. `competitor_strategic_comparison_v1`, version `1.0.0`, produces
advisory territories, gaps, and derived lenses. Each pass has its own model
assignment and effective temperature. Unsupported model items are omitted from
typed findings but remain inspectable in raw model responses and unresolved
review notes.

An inferred competitor pillar is always represented as an inference unless an
explicit source supports the competitor's own architecture. It records
inference strength, confidence, evidence quality, evidence IDs, citations,
research date, and human review state. Competitor-derived lenses likewise
require evidence and confidence.

Territory classifications such as table stakes, emerging pattern, commodity,
or differentiation opportunity are `advisory_only`. They cannot add, remove,
merge, or rename discovery domains or Layer 1 pillars.

## Context compaction

`Layer1DiscoveryContextProjection` includes approved required and optional
lenses, actors, domains, obligations, convergence opportunities, open
questions, and unresolved risks. Human-excluded items are omitted.

`CompetitiveContextProjection` includes only individually approved inferred
pillars, territories, and gaps plus concise source metadata. It excludes raw
page text, raw model responses, rejected findings, and unapproved findings.

Each projection records exact source revision IDs, compiler version, stable
item IDs, inclusion and exclusion rationale, unresolved risks, a deterministic
token estimate, and content hash. Rebuilding from identical sources and the
same compiler version reuses the same projection identity.

## Freshness and provenance

Discovery depends on an exact published brief revision. Republishing Layer 0
marks earlier discovery and applicable research stale and records both the old
and replacement brief revision IDs. Historical content remains available.
Research also retains its own research and verification dates, freshness
state, stale reason, affected checkpoint scope, and selective refresh inputs.
A stale or failed research revision does not invalidate non-competitive
discovery.

Every model call records requested and resolved profile, provider, endpoint,
alias, exact returned model identifier or local filename, local SHA-256 where
available, runtime fingerprint, server process ID where available, prompt key
and version, effective temperature, seed, context and output limits, request
ID, token usage, and elapsed time. An alias such as `default-chat` is therefore
not the sole runtime identity.

The configurable discovery runtime settings are exposed under App and Project
Settings. Independent assignments exist for discovery generation,
cross-domain exploration, practicality review, competitor evidence extraction,
competitor pillar inference, and strategic comparison.

## UI

Layer 0 now has `Product Brief` and `Product Discovery` subtabs. Discovery is
locked until the brief is published and then shows an explicit empty-state
generation action. Structured navigation exposes Overview, Lenses, Actors,
Lifecycle, Product Domains, Enterprise Obligations, Cross-Domain
Opportunities, Competitor Research, Coverage Risks, Open Questions, and
Revision History.

The UI distinguishes baseline, model, competitor, and human sources; candidate,
approved, and published authority; current and stale freshness; and
claim/inference types. It includes annotations, human lenses, lens exclusions,
review summaries, revision comparison, approval/publication/rejection,
regeneration, research modes and budgets, checkpoint progress, completed and
unresolved competitors, source quality, evidence links, inferred pillars,
territories, gaps, finding decisions, scope changes, refresh controls, and
approved research attachment.

## Verification

Focused tests cover the publication gate, exact brief lineage, migration,
stable IDs, baseline coverage, overlapping domains, review dispositions, raw
response retention, immutable publication, separate human/model fields,
regeneration authority, optimistic concurrency, command idempotency, canonical
snapshot, stale propagation, no automatic research or Layer 1 job, distinct
research budgets, evidence-ID enforcement, partial completion, independent
attachment, approved-only compact context, deterministic projections,
authoritative runtime provenance, JSON-safe results, and project
clone/archive/import/purge behavior.

The existing core suite remains the regression proof for unchanged Layer 0,
Layer 1, Layer 2, Layer 3, command, authority, audit, and platform behavior.
SQLite migration and regression coverage is local and complete. PostgreSQL
schema support is implemented through the shared migration adapter, but a live
PostgreSQL integration run requires an available configured server.

## Known limitations and required follow-up

This goal intentionally does not make Layer 1 consume discovery. The exact
follow-up is to:

1. choose the published, current discovery revision at Layer 1 request time;
2. block or warn on stale/missing discovery according to a product-owner
   policy;
3. compile lens-specific slices from `Layer1DiscoveryContextProjection` and
   approved `CompetitiveContextProjection`;
4. schedule required lenses once and optional lenses under explicit budgets;
5. route candidates with provenance back to the source lens and discovery item;
6. define critic authority over discovery-derived candidates without
   overriding human exclusions;
7. update normalization so overlapping discovery domains inform breadth
   without being forced into matching pillars;
8. update exhaustion and stopping logic to measure lens/domain coverage rather
   than raw candidate count;
9. add prompt and outcome evaluation comparing breadth, repetition, and
   category quality with and without discovery context.

Existing Layer 1 behavior deliberately not changed here:

- the published Layer 0 brief still unlocks the Layer 1 workspace;
- Layer 1 generation still uses its existing brief/context compiler;
- its lens scheduler and multi-model assignment behavior are unchanged;
- candidate routing, keep/cut/edit authority, and generation-loop budgeting are
  unchanged;
- overlap critics, normalization, negative memory, and stopping logic are
  unchanged;
- Layer 1 competitor research remains separate from Product Discovery research;
- no Layer 1 job is queued by brief publication, discovery generation,
  discovery approval, discovery publication, or research attachment;
- Layer 2 and Layer 3 prompts and workflows are unchanged.
