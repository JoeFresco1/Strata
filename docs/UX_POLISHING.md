# UX Polishing

## Scope

This note captures polish-level UX issues found during the June 30, 2026 live frontend audit of the Strata app running from `C:\Users\Fresc\Feature_gen`.

The goal here is not a full redesign. It is to keep track of the small-to-medium interaction and presentation issues that make the product feel less finished than it already is.

## Audit Basis

- Live app started locally with the real backend and frontend stack
- Repo-local Playwright harness run from `.tmp-playwright/full_platform_qa.mjs`
- Targeted desktop and mobile captures collected from:
  - `.tmp-playwright/full-platform-qa`
  - `.tmp-playwright/manual-polish-audit`
  - `.tmp-playwright/manual-polish-audit-mobile`

## Priority Findings

### 1. Duplicate competitive intelligence controls on the Project screen

The `Project` tab currently presents competitive intelligence in two places:

- inside the project model overrides/settings panel
- again as its own top-level collapsible section

Why this matters:

- It makes the page feel heavier than it needs to.
- It creates ambiguity about which control is canonical.
- It adds to the sense that the page has too many adjacent controls.

Relevant code:

- `frontend/src/ProjectToolsTab.jsx`
- `frontend/src/ModelSettingsPanel.jsx`

Recommended direction:

- Keep one canonical project-level competitive intelligence control.
- If research actions need their own section, separate "enable/disable" from "run/review/export" clearly.

### 2. Mobile navigation stays open after opening a project

On mobile, opening a project keeps the left rail expanded, so the project starts below the global nav controls instead of prioritizing the active workspace.

Why this matters:

- It wastes vertical space on a small screen.
- It weakens focus when moving from library to project work.
- It makes the first impression of the workspace feel cramped.

Relevant code:

- `frontend/src/App.jsx`

Recommended direction:

- Auto-close the nav rail when opening a project on narrow screens.
- Consider auto-closing after selecting a global action as well.

### 3. Project library cards are too action-dense

Each library card exposes:

- edit
- open
- duplicate
- archive or unarchive

At the same time, the page also includes a top-level create button and a separate library menu trigger.

Why this matters:

- Too many neighboring controls compete for attention.
- The cards feel busy before the user has chosen a project.
- Mobile gets especially crowded.

Relevant code:

- `frontend/src/ProjectShell.jsx`

Recommended direction:

- Keep `Open` as the primary visible action.
- Move lower-frequency actions like edit/archive/duplicate into a per-card overflow menu or secondary reveal.

### 4. Workspace top section spends too much space on chrome before the actual map

The workspace opens with several stacked panels before the user reaches the actual product map:

- workspace intro
- map intro
- collapsed view options
- focus/navigation row

Why this matters:

- The core artifact feels pushed down the page.
- The workspace reads as control-heavy rather than object-first.
- It adds to the "not polished yet" feeling even though the feature works.

Relevant code:

- `frontend/src/LivingWorkspace.jsx`
- `frontend/src/treeDashboard.jsx`

Recommended direction:

- Compress or merge the intro surfaces.
- Pull the highest-value controls closer to the map.
- Make the workspace feel like the primary object, not the panel stack around it.

### 5. Icon glyphs are stored as broken text characters in source

The project library menu and edit affordance use mojibake-like glyph text in source instead of a stable icon strategy.

Why this matters:

- It is brittle across fonts and render contexts.
- It risks visibly broken controls.
- It makes the UI feel improvised even when the layout is otherwise solid.

Relevant code:

- `frontend/src/ProjectShell.jsx`

Recommended direction:

- Replace text glyphs with stable inline SVG or a consistent icon component approach.

## Secondary Notes

- The current visual direction is serviceable and coherent. The issue is not that the app looks bad; it is that the interaction density and control hierarchy do not always feel intentional.
- The main polish risk is not "make it prettier." It is "reduce competing controls, remove duplication, and make the primary action on each screen more obvious."
- The library and project settings surfaces are the biggest near-term payoff areas for polish work.

## Suggested Fix Order

1. Remove duplicate competitive intelligence controls on the `Project` tab.
2. Auto-close mobile nav on project open.
3. Reduce project card action density.
4. Tighten the workspace header/control stack.
5. Replace broken glyph icons with SVG-based controls.

## References

- `frontend/src/App.jsx`
- `frontend/src/LivingWorkspace.jsx`
- `frontend/src/ModelSettingsPanel.jsx`
- `frontend/src/ProjectShell.jsx`
- `frontend/src/ProjectToolsTab.jsx`
- `frontend/src/treeDashboard.jsx`
