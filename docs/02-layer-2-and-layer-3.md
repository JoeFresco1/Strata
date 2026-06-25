# Layer 2 And Layer 3

Layer 2 and Layer 3 should behave as controlled descents from the selected and approved items above them.

## Layer 2

## Layer 2: Functional Subfeatures & Core Components

Layer 2 executes a **convergent, downward expansion** of the system architecture. Rather than broadening the product's scope, this phase deeply explores the functional requirements of the validated Layer 1 modules, mapping out concrete system capabilities while rigorously preventing cross-pillar redundancy.

### Key Objectives & Execution Logic

* **Scoped Pillar Deep-Dives:** The generation engine isolates and expands *only* the pillars explicitly retained or prioritized by the user during the Layer 1 pruning phase. 
* **Comprehensive Subfunctional Mapping:** For each active pillar, the system systematically generates highly specific subfeatures across critical operational vectors, ensuring the model evaluates:
    * *Core Workflows & Automation:* Primary user actions and background processes.
    * *Edge-Case Mitigation:* Boundary conditions and error handling.
    * *Administrative & Governance Controls:* Role-based access, audit logs, and internal configurations.
    * *Data Engineering & Integrations:* Data ingestion models, schema structures, reporting metrics, and external API touchpoints.
* **Contextual Saturation Guardrails:** Applies the same semantic compression and information saturation logic developed in Layer 1. However, the context window is strictly **scoped to the parent pillar lineage** to maintain deep vertical specificity without diluting token efficiency.
* **Negative Cache Memory (Idea Preservation):** Formally stores and tokenizes all human-rejected concepts in a local cache. This prevents the generator and critic agents from entering recursive loops or regenerating previously discarded architectures in future iterations.

## Layer 3: System Integration & Architectural Contracts
## Layer 3: Relationship Modeling & Topology Matrix

Layer 3 maps the cognitive relationship graph across the validated product ecosystem. Instead of defining technical architecture (such as API endpoints or schemas), this phase exposes the non-technical dependencies, data flows, risks, and value drivers of each subfeature. The output of this layer transforms a flat list of features into an interconnected Product Knowledge Graph.

### Key Objectives & Execution Logic

* **Dependency & Enablement Mapping:** For every approved subfeature, the system identifies its prerequisites and downstream impacts within the product ecosystem:
    * *Requires:* What other capabilities, inputs, or user actions must exist for this feature to function?
    * *Enables:* What advanced capabilities, automations, or future modules are unlocked by implementing this feature?
* **Product Risk & Value Attribution:** The engine evaluates the human and business dynamics of each feature node by generating:
    * *Core Risks & Assumptions:* Critical vulnerabilities, edge-case failure modes, or external dependencies that could break the user experience.
    * *Value Drivers:* Explicit user value (e.g., efficiency gains, cost reductions) and business value (e.g., conversion drivers, retention vectors).
* **Deterministic Graph Compilation:** Compiles the entire product footprint into an interconnected topology matrix (JSON Graph). This artifact serves as an upstream "Source of Truth" that downstream execution tools (PRD writers, execution agents, codebase builders) can ingest to understand product context without hallucinating requirements.

## Review & State Persistence Behavior

* **Unified State Workflow:** The user reviews Layer 2 and Layer 3 nodes using a consistent state manipulation workflow: `Keep`, `Cut`, `Rename`, or `Prioritize`.
* **Graph Integrity Retention:** If a user renames, moves, or adjusts the priority of a parent pillar or subfeature, the system dynamically shifts the node labels while preserving the underlying relational vectors (dependencies, risks, and enablers).
* **Negative Matrix Caching:** Concepts, dependencies, or risks explicitly rejected by the human during review are stored in a local negative cache to ensure subsequent generation cycles do not re-introduce discarded product paths.