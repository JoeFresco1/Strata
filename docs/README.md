# Strata Product and Architecture Documentation

This folder defines the current production behavior and architecture for Strata.

The production scope now runs through Layer 3. Layer 3 is the Feature Expansion Layer: a persisted, reviewable product-definition step where approved Layer 2 features are broken into selectable subfeatures, options, limits, validation rules, and overlap notes.

## Files

- `00-overview.md`: product intent, operating principles, and non-goals
- `01-layer-1-discovery.md`: how pillar discovery should broaden, cluster, and stop
- `02-layer-2.md`: current graph-native Layer 2 behavior and review contract
- `03-model-sequencing.md`: how multiple local models should be used in sequence
- `04-storage-and-memory.md`: PostgreSQL, pgvector, durable memory, and provenance rules
- `05-ui-and-export.md`: the review workflow and export behavior
- `layer architecture.md`: cross-layer agentic flow, user interaction, generation, and memory handling by layer
- `PRODUCTION_ARCHITECTURE.md`: supported runtime, service boundaries, persistence, and canonical data flows
