# UI And Export

Strata should feel like a working review tool, not a chat app.

## Main flow

1. Create a project from a product idea.
2. Broaden Layer 1 until it saturates.
3. Review pillars and prune them.
4. Broaden Layer 2 from the approved pillars.
5. Review subfeatures and prune them.
6. Generate Layer 3 specs from the approved subfeatures.
7. Export the whole tree to Markdown and JSON.

## UI behavior

- Show the current project clearly and keep the workflow in tabs or sections.
- Surface duplicate warnings, canonical family data, quality scores, and source provenance on pillar nodes.
- Let the user rename nodes in place.
- Let the user set status and priority without hidden side effects.

## Export behavior

- Export the current tree as Markdown for quick reading.
- Export a JSON copy for downstream tooling.
- Include the project idea and the tree structure in the export.
