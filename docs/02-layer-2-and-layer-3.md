# Layer 2 And Layer 3

Layer 2 and Layer 3 are controlled descents from approved upstream product
structure. They stay product-definition focused: they describe capabilities,
relationships, configuration choices, overlap decisions, and option state before any implementation-spec
or code-generation system takes over.

## Layer 2: Feature Graph

Layer 2 expands only approved Layer 1 pillars into concrete product
capabilities. The output is a provenance-aware feature graph, not a tree of
implementation tasks.

### Key Objectives

- Expand only pillars the user kept, prioritized, or approved.
- Generate capabilities at product-feature granularity, avoiding pages,
  endpoints, schemas, code tasks, and Layer 1-sized modules.
- Give each feature one owner pillar while preserving cross-pillar relationships
  as graph edges.
- Track coverage families, aliases, scope contracts, ambiguity, integrity
  signals, shared concerns, competitor evidence, and rejection memory.
- Keep candidates reviewable instead of silently deleting ambiguous, duplicate,
  or off-scope ideas.

### Review And Persistence

- Users can keep, cut, merge, rename, reprioritize, approve, and mark features
  for review.
- Duplicate recommendations, ownership changes, and relationship changes remain
  separate review decisions.
- Rejected and merged-away concepts remain available as anti-rediscovery memory.
- Competitive evidence is cited and advisory; it does not automatically decide
  product scope.

## Layer 3: Feature Expansions

Layer 3 turns approved Layer 2 features into persisted Feature Expansions. It
defines what can go inside the feature as product-level options while explicitly
excluding implementation specifications.

### Key Objectives

- Generate expansions only for approved Layer 2 features.
- Use compact Layer 0 context, the parent pillar, approved siblings, and
  relevant Layer 2 graph edges as bounded context.
- Define feature intent, grouped subfeatures, configuration options, validation
  rules, limits, dependencies, overlap links, and open questions.
- Default options to undecided so users choose include, exclude, or edit rather
  than accepting a hidden generated scope.
- Persist expansions, option state, review actions, and provenance independently
  of chat history.

### Review And Delivery

- Users can edit feature intent, add/remove groups, include/exclude options,
  mark overlaps, approve, reject, and export expansions.
- Approved expansions can be exported as structured JSON with complete Layer
  0/1/2 lineage and selected/excluded option state.
- Layer 3 must not generate target-product APIs, database schemas, components,
  test cases, wireframes, user stories, architecture diagrams, or coding tasks.
