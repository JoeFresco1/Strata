# UX Review: Project Settings, Guides, and Landing

Date: 2026-06-29
Reviewer: Codex as senior UX engineer/designer
Scope: live localhost review of the Strata project library landing page, project-scoped settings, and Guide modal.

## Evidence

- API: `http://127.0.0.1:8000/api/projects` returned 200.
- Frontend: `http://127.0.0.1:5173` rendered through Vite.
- Browser pass: Playwright Chromium desktop `1440x1000` and mobile `390x844`.
- Captures:
  - `.runtime/ux-audit/landing-desktop.png`
  - `.runtime/ux-audit/landing-mobile.png`
  - `.runtime/ux-audit/project-settings-top.png`
  - `.runtime/ux-audit/project-settings-mobile.png`
  - `.runtime/ux-audit/guide-modal-open.png`

## Executive Read

The current UX is functional but still feels like an internal admin console that exposes implementation structure directly to the user. The app has many capable surfaces, but it does not consistently answer three basic user questions:

1. Where am I?
2. What matters right now?
3. What action should I take next?

The highest-leverage first fix should be Project Settings. It is the clearest example of the broader problem: critical decision controls are buried inside generic navigation, competing panels, repeated labels, and mixed-purpose tooling. Landing and Guides need cleanup too, but settings is the area most likely to cause wrong configuration, confusion, and support burden.

## Area 1: Project Settings

### Current Experience

Path observed: open project -> top tabs -> `Project` -> `Project settings` disclosure -> `Project Model Overrides`.

The page currently mixes:

- project model/runtime overrides
- competitive intelligence master switch
- export actions
- competitive research settings
- advanced diagnostics
- raw generation memory

This makes the `Project` tab feel like a drawer of leftovers rather than a purposeful project control center.

### Major UX Problems

1. The label `Project` is too vague for the tab.
   Users looking for settings do not naturally know that settings live under `Project`, especially when there is also a global `Settings` button in the side rail.

2. The hierarchy repeats itself.
   The user sees `Project` -> `Project settings` -> `Project Model Overrides`. That is three conceptual wrappers before the first real decision.

3. Save placement is visually detached from the fields.
   On desktop, `Save Project Overrides` sits in a header-like card above the controls. On mobile, it appears before the user has reviewed the choices. It is easy to miss what will be saved.

4. The page asks users to understand runtime architecture before making a simple choice.
   The compute-mode cards are better than raw settings, but the supporting text still leans on implementation terms like model work, orchestration, local concurrency, API profiles, fanout, and routing.

5. Dangerous or high-impact decisions are not separated from ordinary utilities.
   A switch that changes whether competitive intelligence runs is placed near export and diagnostics surfaces. It should be part of a deliberate project behavior section with visible downstream impact.

6. Advanced controls are correctly collapsed, but the surrounding page still feels advanced.
   Collapsing details is not enough if the page framing, labels, and neighboring sections still read like internal machinery.

7. Mobile becomes a long vertical settings tunnel.
   The basic settings are readable, but the user has to travel through large cards before seeing the rest of the project controls. The tab row wraps acceptably, but the page lacks a compact local navigation or summary.

### Recommended Redesign

Make this a real project control center, not a mixed tools tab.

Rename the tab from `Project` to `Settings` or `Project Settings`. If global settings remain in the rail, label that `App Settings` so the distinction is explicit.

Split the current tab into clear sections:

1. Project Behavior
   - Compute mode
   - Competitive intelligence
   - Assistant/research behavior summary
   - Save bar colocated with dirty state

2. Exports
   - Full project export
   - Layer 2 export
   - Project archive export
   - Last export result

3. Diagnostics
   - Diagnostics export
   - Generation memory
   - Raw debug details

The first screen should show a compact summary:

- Runtime: Local-first
- Generation: Local
- Research: Local
- Assistant: Local
- Competitive intelligence: On
- Unsaved changes: No

Then provide `Edit runtime behavior` or inline controls below it. This lets a returning user confirm state at a glance.

### First Implementation Slice

Start with the structure, not visual polish:

1. Rename the tab and global side-rail labels to remove ambiguity.
2. Replace the nested `details` wrapper with a top-level settings layout.
3. Move `Save Project Overrides` into a sticky or section-local action row that appears after the controls on mobile.
4. Split exports and diagnostics into separate cards/sections with clearer headings.
5. Add a short project-settings summary strip above the controls.

## Area 2: Guides

### Current Experience

The Guide modal is now broader and more current than the old small guide, but it is still a static encyclopedia. It describes surfaces rather than helping the user decide what to do.

### Major UX Problems

1. The entry point is hidden.
   Guide is behind an unlabeled hamburger when the rail is collapsed. A first-time user is unlikely to discover it when confused.

2. It is too generic to be useful in the moment.
   The guide explains that Layer 2 exists, but it does not answer context-sensitive questions like "why is this button disabled?" or "what should I do before generating Layer 2?"

3. The card grid gives equal weight to everything.
   Project library, Layer 3, analytics, provider readiness, and data ownership all have similar visual weight. That flattens the product's mental model.

4. There are no actions.
   The guide does not deep-link, switch tabs, start setup, open project settings, or highlight next steps.

### Recommended Redesign

Keep a short global guide, but add contextual guidance where work happens.

Global Guide should become:

- `Start a project`
- `Work through Layers 0-3`
- `Manage models and settings`
- `Export or hand off work`
- `Troubleshoot readiness`

Each section should include one primary action where possible, such as `Open project settings`, `Go to Layer 0`, or `Open diagnostics`.

Inside each major screen, add small contextual empty states and blocked-state explanations. The best guide is usually the one next to the disabled or confusing control.

## Area 3: Landing Page

### Current Experience

The Project Library is usable and improved from a raw list. Search, view, sort, create, and card actions are visible. Mobile mostly holds together.

### Major UX Problems

1. The landing page is visually dominated by project cards, not project intent.
   It shows inventory before helping the user choose a path: continue recent work, start manually, import, or inspect archived work.

2. The metadata is noisy.
   `Opened Never`, node counts, pillar counts, clone source, and short project ID compete with the project summary. Some of this should be secondary detail.

3. The menu icon is ambiguous.
   On desktop and mobile, the import action is hidden behind a hamburger-like icon that looks like navigation, not project library overflow.

4. Duplicate smoke-test projects make the product feel messy.
   The current data set amplifies the problem: repeated `Embedding Smoke` cards and smoke projects make the first screen look less like a product and more like test residue.

5. Loading state is extremely blank.
   The first screenshot caught `Loading Strata` centered on a near-empty page. That may be acceptable for a split second, but it becomes trust-eroding if startup lingers.

### Recommended Redesign

Add a compact command header:

- Continue recent project
- New project
- Import archive
- View archived

Then make the project grid more scannable:

- promote last opened/updated as one clear timestamp
- hide project ID behind secondary details
- show node/pillar counts as small structured stats only when useful
- de-emphasize duplicate/archive actions until hover or overflow on desktop
- use a clearer overflow button label/icon for less common actions

For empty/loading states, show the shape of the app instead of a blank page:

- skeleton header
- skeleton project cards
- short local connection status
- retry action if startup exceeds a threshold

## Priority Order

1. Project Settings IA and labels
2. Project Settings save/summary behavior
3. Guide entry point and task-oriented structure
4. Landing page card metadata and command hierarchy
5. Loading state trust polish

## Design Principle For The Next Pass

Do not expose the implementation hierarchy as the user hierarchy. Users need to manage a project, decide how much automation to use, and move work toward export. The UI should group controls by those jobs, not by backend subsystems.
