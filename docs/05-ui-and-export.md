# UI And Export

Strata should feel like a guided product-architecture workspace.

## Main flow

1. Create a project and shape the canonical Layer 0 brief.
2. Publish the brief.
3. Generate and broaden Layer 1 until coverage saturates.
4. Review pillars and select what should descend.
5. Generate the Layer 2 feature graph.
6. Review scope, ownership, overlap, relationships, and competitor evidence.
7. Generate and review Layer 3 Feature Expansions for approved features.
8. Include, exclude, edit, or add expansion options until the feature shape is clear.
9. Export the project, Layer 2 graph, approved Layer 3 manifest, diagnostics,
   or portable archive.

## UI behavior

- Organize the current production workflow around one living Workspace plus Brief, Feature Expansion, and Project utilities.
- Let users switch between Map and Table without losing the selected entity or branch context.
- Restore the last selected entity, view mode, and filters when a project is reopened.
- Show only actionable stages by default and progressively disclose future or advanced controls.
- Surface duplicate warnings, canonical family data, quality scores, and source provenance on pillar nodes.
- Make Layer 2 review graph-aware and decision-first.
- Keep Layer 3 option groups, include/exclude choices, overlap review, open questions, and approval state in one workspace.
- Keep runtime routing, model profiles, prompt editing, diagnostics, and raw memory behind advanced disclosure.
- Keep the assistant available across the project without requiring users to configure orchestration before asking a question.
- Keep lifecycle operations explicit: archive/unarchive, clone, portable archive
  import/export, and destructive purge should be deliberate actions with clear
  status or confirmation.

## Export behavior

- Export the current project as Markdown for quick reading.
- Export a JSON copy for downstream tooling.
- Export the Layer 2 graph separately when graph-level provenance and review state are needed.
- Export approved Layer 3 Feature Expansions as structured JSON with option selection state, overlap notes, provenance, and Layer 0/1/2 lineage.
- Export diagnostics with redaction controls and deterministic manifests.
- Export portable project archives for import into another Strata installation.
- Show output paths and completion state in the UI.
