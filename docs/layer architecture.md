# Layer Architecture

This document describes Strata's current production layer model as an agentic system.

The production scope is Layer 0 through Layer 3.

## Overall agentic process

Strata works as one bounded, layered architecture rather than one freeform autonomous agent.

1. Layer 0 creates the canonical product brief.
2. Layer 0 research adds cited market context to that brief.
3. Product Discovery turns the published brief into the required actor, lifecycle, domain, obligation, risk, and exploration lenses.
4. Layer 1 explores those lenses independently, retains useful non-pillar territory, and synthesizes multiple candidate pillar architectures.
5. Human review separately selects and explicitly applies one architecture before descending into Layer 2.
6. Layer 2 turns the applied pillars and their retained territory into a graph of concrete product capabilities.
7. Layer 2 research adds cited competitor evidence to active features.
8. Layer 3 expands approved Layer 2 features into product-level Feature Expansions while preserving their architecture lineage.
9. Human review includes, excludes, edits, and approves expansion options for downstream export.
10. The assistant operates across the project as a bounded reader, synthesizer, and action proposer rather than as a separate layer owner.

The important architecture rule is that each layer narrows uncertainty differently:

- Layer 0 reduces ambiguity in the product definition.
- Layer 1 reduces ambiguity in the major architecture of the product.
- Layer 2 reduces ambiguity in the concrete capability graph beneath that architecture.
- Layer 3 reduces ambiguity in what each approved capability means as product behavior, configuration, lifecycle, and relationships.

## Layer 0

### What Layer 0 does

Layer 0 defines one canonical product brief. It is the only approved source of truth for the product idea before downstream generation begins.

It captures:

- product concept
- target users
- goals and outcomes
- constraints
- preferred directions
- rejected directions
- known competitors
- open notes

### Overall agentic process

Layer 0 is an intake and clarification loop.

1. The user describes the product in Plan mode or edits fields in Form mode.
2. The Layer 0 service extracts structured updates into the same canonical brief.
3. The system returns a recap, focus area, and next questions.
4. The user keeps refining until the brief is coherent enough to publish.
5. Publishing freezes the current brief as the active downstream input and queues Layer 0 research.

### How users can interact

Users can interact with Layer 0 in two ways:

- Plan mode: a conversational intake flow where the system asks follow-up questions and applies structured updates.
- Form mode: direct editing of the canonical brief fields.

These are not separate drafts. Both write to the same brief object.

The user remains in control of when the brief is good enough to publish. Publication is the explicit gate into Layer 1.

### How it is generated

Layer 0 generation is not open-ended brainstorming. It is structured extraction and guidance.

- A Layer 0 planning prompt turns the latest conversation turn plus current brief state into structured updates.
- The system merges those updates into the canonical brief.
- The same process also produces guidance fields such as recap, next questions, focus area, and confidence.
- After publishing, local research jobs gather cited market findings tied to the published brief.

### Competitive intelligence in Layer 0

Layer 0 competitive intelligence is a market-landscape pass, not a rating pass.

- The user-provided `known_competitors` list is the highest-trust input.
- The system can suggest additional adjacent competitors, then resolves and crawls a focused public-page set.
- The resulting `market_landscape` finding stores cited evidence plus:
  - `competitors`
  - `major_capability_themes`
  - `market_saturation_notes`
  - `whitespace_opportunity_notes`
- Layer 0 currently does not compute a formal numeric market score or weighted competitor rating.
- Its job is to give the rest of the stack grounded market context: who is in the space, what capability themes repeat, where the market looks saturated, and where whitespace may exist.

### How memory is handled

Layer 0 keeps two distinct memory types:

- durable canonical brief state
- conversational planning history

The architecture should not treat the raw chat transcript as the source of truth. The brief is canonical; the transcript is support context.

Memory is bounded by:

- keeping the structured brief as the primary prompt input
- storing conversation history durably without replaying all of it every turn
- carrying forward only the latest guidance and relevant brief deltas into model context
- persisting research pages, chunks, findings, and citations for later review without stuffing them back into every prompt

## Layer 1

### What Layer 1 does

Layer 1 first discovers product territory, then synthesizes major product-pillar architectures. Territory can be pillar-shaped, cross-cutting, operational, governance-oriented, actor-specific, or suitable for a later layer; it is never forced into a pillar simply to survive.

Layer 1 exists to answer both: "What meaningful product territory exists?" and "Which coherent pillar architecture should organize it?"

### Overall agentic process

Layer 1 is a resumable, breadth-first exploration and synthesis loop.

1. Start from the exact published Layer 0 brief and exact published Product Discovery revision.
2. Run every required Discovery lens independently with bounded context, contrastive exclusions, source attribution, and configured retries.
3. Persist every raw response, attempt, candidate, disposition, runtime setting, and model provenance before later judgment.
4. Normalize and assess candidates without deleting or collapsing the raw record.
5. Cluster semantic families, track lens coverage, and retain useful territory at typed destinations beyond pillars.
6. Run an adversarial pass and apply explicit stopping rules; budget exhaustion never masquerades as saturation.
7. Synthesize at least two immutable, mapped architecture options and critique them globally.
8. Let a human select an option without changing the project map.
9. Apply the selected option only through a second explicit confirmation with optimistic concurrency and risk acknowledgment.

### How users can interact

Users interact with Layer 1 as a review and steering surface rather than a hidden background process.

They can:

- generate, approve, and publish Product Discovery before exploration
- start or safely resume a checkpointed territory run
- review raw candidates, destinations, coverage, adversarial findings, and architecture options
- select an architecture as a non-mutating decision
- explicitly apply the selected architecture to the project map
- cut, keep, merge, rename, and prioritize pillars
- inspect provenance such as source lens, source model, overlap, and quality signals
- review cited Layer 1 competitor coverage tied to specific pillars

Layer 1 competitive intelligence is surfaced directly in pillar review. Each pillar can show:

- a competitor coverage matrix
- an implementation profile scorecard
- cited evidence snippets and whitespace notes
- stale-research warnings after a pillar is edited

Applying an architecture preserves the prior pillars as cut historical nodes, creates the new kept pillars atomically, marks descendants of superseded pillars stale, and records the exact application, selection, mappings, retained territory, actor, and command. The applied architecture becomes the descent boundary for Layer 2.

### How it is generated

Layer 1 uses independent typed passes rather than one pillar prompt.

- Product Discovery defines the complete required lens queue and attributable source inventory.
- Each lens call receives only its bounded projection, prior exclusions, and the territory schema.
- Valid candidates are checkpointed immediately; malformed or timed-out attempts remain inspectable and retryable.
- Normalization and assessment create append-only projections over immutable raw candidates.
- Clustering, coverage, and adversarial analysis expose gaps without erasing dissenting territory.
- Architecture synthesis maps territory into multiple options while retaining significant non-pillar territory.
- Selection and application remain separate human commands.

The architecture is intentionally breadth-first. Layer 1 should exhaust meaningful pillar families before going deeper.

### Competitive intelligence in Layer 1

Layer 1 competitive intelligence has two parts: a competitor coverage matrix and an engineering-oriented implementation profile.

The competitor coverage matrix is built per pillar and records, for each competitor:

- `coverage_status`: `supported`, `partially_supported`, `unclear`, or `not_evident`
- `adoption_level`: `common`, `emerging`, `unclear`, or `rare`
- `confidence`: `0-100`
- `summary`
- cited `evidence`
- `whitespace_note`

Those values come from a focused public crawl plus a simple signal score derived from how strongly competitor page language overlaps the pillar.

The implementation profile then translates that market evidence into a scorecard with:

- `confidence`: `0-100`
- `indexed_score`: `0-100`
- six required `ratings`, each on a `1-10` scale:
  - `build_complexity`
  - `infrastructure_demand`
  - `maintenance_burden`
  - `integration_complexity`
  - `operational_risk`
  - `competitive_research`
- `summary`
- `implications`

This means Layer 1 competitive intelligence is not only asking "do competitors appear to have this pillar?" It is also asking "how hard does this pillar look to build, operate, integrate, and differentiate?"

### How memory is handled

Layer 1 memory is source-typed and compressed.

It includes:

- exact published brief and Product Discovery revision lineage
- immutable raw responses, attempts, candidates, and model-file provenance
- complete current and historical candidate dispositions
- persisted pillar memory
- canonical family and overlap memory
- quality and assessment signals
- rejected or quarantined candidates
- coverage summaries and saturation state
- research evidence attached to pillars
- architecture options, critic findings, selection events, and application history
- retained non-pillar territory passed to downstream layers

The system should not replay every prior generation round into the model. Instead it should pass bounded memory packets such as:

- existing canonical pillars
- compressed family summaries
- recent raw candidates
- known overlap clusters
- uncovered areas or critic summaries
- rejected ideas that should not be rediscovered

Embeddings and canonical families support deduplication, but the user still decides whether similar pillars should be merged, kept separate, or removed.

## Layer 2

### What Layer 2 does

Layer 2 builds the concrete feature architecture beneath approved Layer 1 pillars.

It does not generate tree-only child nodes or implementation tasks. It generates canonical product capabilities with explicit ownership, relationships, scope signals, and review state.

Layer 2 exists to answer: "What concrete product capabilities make each approved pillar real?"

### Overall agentic process

Layer 2 is a controlled graph-native descent.

1. Start only from kept or prioritized Layer 1 pillars; pillars from different architecture applications cannot be mixed in one generation run.
2. Establish scope contracts and coverage families using the pillar's mapped territory plus retained non-pillar territory from its active architecture application.
3. Run bounded lens passes to create raw feature candidates.
4. Apply integrity, overlap, graph, ambiguity, and negative-cache critics.
5. Persist canonical features, aliases, affinities, relationships, and review signals in graph-native tables.
6. Keep ambiguous or overlapping items reviewable rather than silently deleting them.
7. Run or rerun feature-level competitor research for active features.
8. Let human review decide what is approved, merged, renamed, cut, linked, or exported.

### How users can interact

Users interact with Layer 2 through the living workspace, the entity inspector, the table view, and the review controls.

They can:

- generate Layer 2 from selected pillars
- inspect features in map or table form
- create or edit features manually
- review duplicates, ownership, granularity, shared concerns, and relationships
- keep, cut, merge, rename, reprioritize, approve, and bulk-update features
- rerun selected or full Layer 2 competitor research
- export the reviewed Layer 2 graph

Layer 2 competitive intelligence is exposed in two places:

- the workbench and feature detail view for per-feature evidence and scores
- the competitive-intelligence matrix for feature-by-competitor coverage

Users can also save Layer 2-specific competitors and choose the research mode:

- `known_only`
- `expand_from_known`

The user is the final authority on graph shape. Automated critics surface evidence and recommendations, but they do not silently finalize architecture.

### How it is generated

Layer 2 generation is graph-aware and review-aware.

- Every generation run records its source architecture application and the full exact set of mapped and retained Layer 1 territory IDs.
- A scope-discovery step receives bounded detailed projections of that territory and defines the pillar boundary and coverage families.
- Feature-generation passes create raw candidates under those constraints.
- Critic passes check scope, granularity, ownership, overlap, ambiguity, shared concerns, and graph consistency.
- Canonicalization persists one feature graph with aliases and cross-pillar relationships instead of disconnected trees.
- Research jobs attach cited competitor evidence with run provenance to active features.

Layer 2 generation continues only while there is meaningful uncovered territory and new candidates remain novel.

### Competitive intelligence in Layer 2

Layer 2 competitive intelligence is feature-level and matrix-driven.

Each evidence row for a feature records:

- `competitor_name`
- `coverage_status`: `has_feature`, `partial`, `not_found`, or `unclear`
- `confidence`: `0-100`
- `source_url`
- `evidence_snippet`
- `rationale`
- `source_type`: `manual` or `discovered`
- `research_job_id`

The matrix uses the newest evidence per competitor as the current cell value, while full history is still retained.

Each feature also exposes a derived `competitor_coverage_score` on a `0-100` scale. Right now that score is intentionally simple:

- `has_feature` = `1.0`
- `partial` = `0.5`
- `unclear` = `0.0`
- `not_found` = `0.0`

The score is the average of those weights across the latest evidence set, converted to a percent.

Layer 2 therefore combines market evidence with product-architecture scoring. A feature can simultaneously show:

- `pillar_fit_score` `0-100`
- `distinctiveness_score` `0-100`
- `strategic_value_score` `0-100`
- `implementation_leakage_score` `0-100`
- `competitor_coverage_score` `0-100`

That lets review ask two different questions at once:

- Is this a strong product capability for our architecture?
- Is this capability common, partial, or absent across competitors?

### How memory is handled

Layer 2 memory is scoped, graph-native, and anti-rediscovery.

It includes:

- sibling and cross-pillar feature context
- coverage-family state and exhaustion summaries
- rejected concept memory and negative-cache entries
- duplicate and alias history
- graph relationships and pillar affinities
- competitor evidence and research provenance
- review-action history

Prompt context should stay bounded to the current pillar, current feature family, or current review task. The database stores the full graph history, but model calls should receive only the local slice needed for the next pass.

The full territory lineage remains durable on the generation run even when prompt projections are compacted. This separates lossless audit storage from bounded inference context.

This is what keeps Layer 2 from collapsing into repeated rediscovery or unfocused graph sprawl.

## Layer 3

### What Layer 3 does

Layer 3 is the Feature Expansion Layer. It defines what can go inside an approved Layer 2 feature before any implementation-spec system takes over.

Each expansion includes feature intent, grouped subfeatures, configuration choices, validation rules, limits, dependencies, overlap notes, open questions, review state, and provenance.

Layer 3 does not generate target-product APIs, database schemas, components, regex patterns, test cases, user stories, wireframes, architecture diagrams, or coding tasks.

### Overall agentic process

1. Load only approved Layer 2 features.
2. Resolve the feature's Layer 2 generation run and active Layer 1 architecture application.
3. Generate a draft expansion from bounded Layer 0, mapped Layer 1 territory, parent-pillar, sibling-feature, and graph-edge context.
4. Group the next-level possibilities into options such as response type, validation rules, limits, display behavior, admin controls, integrations, or workflow variants.
5. Default options to undecided so the user can explicitly include, exclude, edit, add, or remove them.
6. Let the user mark option overlap with active Layer 2 features.
7. Let the user approve, reject, or return an expansion to review.
8. Export approved expansions with full Layer 0/1/2 lineage.

### How users can interact

The Feature Expansion workspace shows eligible features and existing expansions. Users can:

- generate one or more expansions
- inspect and edit feature intent
- include, exclude, add, remove, or rewrite grouped options
- mark overlap with active Layer 2 features
- capture open product questions
- approve, reject, or return an expansion to review
- export approved expansions as structured JSON

### How memory is handled

Feature expansions, option state, review actions, and provenance are canonical database records. Raw chat history is not the source of truth.

Generation context is bounded to:

- compact Layer 0 brief context
- the active Layer 1 architecture application and mapped territory projection
- the parent Layer 1 pillar
- the selected approved Layer 2 feature
- approved sibling features
- relevant Layer 2 graph relationships
- the current card only when regenerating selected sections

The expansion provenance stores the exact architecture application, its content hash, the source Layer 2 generation run, and the full Layer 1 territory ID set. An application dependency lets later upstream changes mark the expansion stale without deleting its history.

## Cross-layer assistant

### What it does

The assistant is a shared project service, not a replacement for the layer pipeline.

It helps users:

- ask questions about the current project state
- retrieve and synthesize evidence across layers
- compare branches, pillars, and features
- navigate to relevant entities
- propose bounded mutations that require explicit confirmation

### How users can interact

Users can open the assistant from anywhere in the project, keep multiple durable conversations, reference older threads, and choose whether to use deeper specialist analysis.

### How it is generated

The assistant uses a bounded orchestration flow:

1. plan the reads and any specialist work
2. retrieve project evidence
3. run optional specialist analysis
4. synthesize a cited answer
5. emit action proposals instead of silent writes

### How memory is handled

Assistant memory is durable but compacted.

It keeps:

- conversations
- messages
- retrieval traces
- citations
- runs and specialist runs
- action proposals
- compacted conversation summaries

The assistant should not depend on full unbounded chat replay. Older turns are compressed, retrieval is content-based, and only the relevant project slice is loaded for a given answer.

## Layer boundaries and memory boundaries

The architecture depends on strict boundaries:

- Layer 0 owns product-definition memory.
- Layer 1 owns pillar-discovery memory.
- Layer 2 owns feature-graph and review memory.
- Layer 3 owns capability-definition, decision, relationship, readiness, and review memory.
- The assistant reads across those layers but does not replace their canonical state.

The database keeps the durable record. Prompt context stays bounded, scoped, and purpose-built for the current operation.
