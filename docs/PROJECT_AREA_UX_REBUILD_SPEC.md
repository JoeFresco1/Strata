# Project Area UX Rebuild Spec

Date: 2026-07-02
Status: implementation guide for the project-area rebuild

## UX Contract

The project area is a guided product-building workbench, not a long stack of panels. The persistent top stepper is the primary orientation system:

`Layer 0 Product Plan -> Layer 1 Pillars -> Layer 2 Features -> Layer 3 Capability Design -> Export`

Each step shows one of these states: current, ready, locked, needs review, or blocked. Locked steps must say what unlocks them. The map/table canvas remains the visual center for all steps.

## Desktop Wireframe

```text
Project header
Stepper + Workflow menu
------------------------------------------------------------
Left controls       Center map/table canvas       Right inspector
collapsible         map remains visible           opens on selection
step actions        global Map/Table mode         edits/review/details
primary CTA         compact canvas tools          partial-width dock
```

On bubble click, the right inspector docks open without replacing the map. The left controls auto-collapse to a slim state. Users can reopen or pin either side panel.

## Mobile Wireframe

The stepper becomes a horizontal scroll rail. The canvas is first. Controls and inspector become stacked drawers/bottom-sheet sections:

1. Stepper
2. Map/table canvas
3. Current step controls
4. Selected item inspector

## Layer 0 Product Plan

First visit shows a ghost Layer 0 bubble and a clear `Start Product Plan` action. The left panel contains `AI Chat` and `Form`, and the chat heading is `Product Plan Conversation`.

After Layer 0 is published and downstream layers exist, Layer 0 is hard-locked by default. `Unlock Layer 0` opens an explicit confirmation modal that explains downstream impact. Unlocking is an escape hatch, not the default editing path.

Clicking the Layer 0 bubble opens the right inspector with product idea, target users, constraints, goals, competitors, preferred directions, rejected directions, and notes. Publishing remains the big in-context CTA for this step.

## Layer 1 And Layer 2 Review

Every pillar or feature supports per-card actions: `Accept`, `Reject`, `Edit`, `Research`, and `Merge`.

Table mode adds checkboxes and a bulk bar that appears only after selection. Bulk actions are `Accept`, `Reject`, `Research`, `Combine`, and `Discard`.

Combine is not drag-and-drop. Users select two or more items, choose `Combine`, pick a winner, preview the merged summary, then mark losing items as `merged`.

## Layer 3 Capability Design Mini-Spec

Layer 3 must read as a product-definition workbench, not a raw JSON editor.

Capability cards need to show and support:

- Purpose and archetype
- Product behaviors
- Configurable options and supported variants
- User-facing states and lifecycle
- Validation and constraint concepts
- Dependencies
- Relationships to Layer 2 source features and other capability cards
- Open decisions with question, context, options, resolution, and status
- Risks, edge cases, and overlap/conflict signals
- Evidence, citations, pressure test, coverage gaps, competitive analysis, and readiness

The right inspector is tabbed: `Overview`, `Behavior`, `Options & States`, `Relationships`, `Decisions`, `Risks`, `Evidence`, `Readiness`, and `Advanced`.

Default editing uses structured list editors. Raw JSON remains available only under `Advanced`.

Layer 3 approval is blocked when there are unsaved edits, stale pressure tests, unresolved required decisions, stale or inactive Layer 2 sources, or blocking readiness issues.

## Export

Export is the final step, not a subpanel inside Layer 3. The central canvas/table shows export-ready cards and blockers. The main CTA is `Create Spec Kit Bundle`. Secondary exports remain available from the workflow menu or export step.

## Empty And Error States

- Blank Layer 0: ghost product bubble, `Start Product Plan`, and brief guidance.
- No Layer 1: explain that publishing Layer 0 unlocks manual pillar entry and generation.
- No Layer 2: explain that accepted pillars unlock feature generation/manual add.
- No Layer 3: explain that approved Layer 2 features unlock capability design.
- Generation or competitive-intelligence failure: inline error with reason, retry action, and job detail pointer.

## Implementation Notes

Build on the existing React workspace components. Do not create a parallel product area. Persist new UI preferences through the existing workspace-state payload so older projects continue to open.
