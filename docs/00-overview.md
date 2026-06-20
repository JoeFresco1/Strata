# Strata Overview

Strata is a local recursive product-spec generator that turns one product idea into a tree of pillars, subfeatures, and implementation specs.

The product should behave like a broad discovery engine with human-in-the-loop pruning. It should expand aggressively first, then let the user cut, merge, rename, and prioritize before descending to the next layer.

## Core principles

- Be local-first and keep everything on the user’s machine.
- Favor breadth before depth.
- Stop when the current layer is saturating instead of generating endless variations.
- Keep the user in control at layer boundaries.
- Preserve provenance so the user can see which model, lens, and round produced each item.
- Prefer structured JSON output and SQLite persistence over ad hoc text blobs.

## Non-goals

- Do not become an autonomous agent swarm.
- Do not regenerate forever.
- Do not auto-delete questionable items.
- Do not make Layer 1 behave like Layer 2.
- Do not depend on external cloud services for the core workflow.
