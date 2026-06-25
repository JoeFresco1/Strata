# Strata Overview

Strata is a local-first product discovery and feature-architecture platform. It turns an initial idea into a canonical brief, a reviewed set of product pillars, and a graph of concrete product capabilities.

## Current production scope

### Layer 0: canonical brief

- Use one structured brief as the source of truth.
- Support conversational planning and direct form editing against that same brief.
- Require explicit publication before Layer 1 generation.
- Preserve known competitors, constraints, users, goals, preferred directions, rejected directions, and notes.

### Layer 1: product pillars

- Explore broadly across bounded lenses and model phases.
- Normalize and assess candidates before persistence.
- Preserve model, lens, round, quality, overlap, and research provenance.
- Keep human review in control of what advances.

### Layer 2: feature graph

- Descend only from kept or prioritized pillars.
- Store concrete capabilities as canonical graph entities, not tree-only subfeature nodes.
- Track ownership, aliases, relationships, scope contracts, coverage families, shared concerns, ambiguity, rejection memory, and competitor evidence.
- Require human review for ambiguous, overlapping, or off-scope candidates.

Layer 3 is the Capability Design Layer. It expands approved Layer 2 features into product-level definitions with behavior, configuration, relationships, risks, decisions, and downstream-readiness review while explicitly excluding implementation specs.

## Core principles

- Local-first by default, with explicit local, API, or blended execution intent.
- Breadth before depth.
- Bounded generation with measurable stop conditions.
- Human approval at layer boundaries.
- Durable provenance and review history.
- PostgreSQL as the production source of truth.
- Structured model output with validation and repair.
- One coordinated project assistant rather than separate layer-specific chat systems.

## Non-goals

- Unbounded autonomous agent swarms.
- Endless regeneration.
- Automatic deletion of uncertain candidates.
- Flattening Layer 1 and Layer 2 into the same data model or generation process.
- Requiring cloud services for the core workflow.
