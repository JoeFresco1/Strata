# Workspace UX Review: Project-Area Tabs Outside The Layer Flow

Date: 2026-06-30
Reviewer: Codex
Scope: live localhost review of the project-area tabs that sit outside the layer progression: `Workspace`, `Analytics`, and `Project Settings`.

## Evidence

- API health: `http://127.0.0.1:8000/api/health` returned `{"ok": true, "llm_message": "Reachable via /v1/models"}`.
- Frontend: `http://127.0.0.1:5173` returned HTTP 200.
- Live project used for review: `Deep Research Smoke 2026-06-17 Copy`.
- Browser pass: headless Playwright via local Edge at desktop `1440x1100` and mobile `390x844`.
- Captures:
  - `.runtime/ux-audit/project-area-tabs-2026-06-30/desktop-workspace-top.png`
  - `.runtime/ux-audit/project-area-tabs-2026-06-30/desktop-analytics-top.png`
  - `.runtime/ux-audit/project-area-tabs-2026-06-30/desktop-project-settings-top.png`
  - `.runtime/ux-audit/project-area-tabs-2026-06-30/mobile-project-settings-top.png`
- Structured inspection:
  - `.runtime/ux-audit/project-area-tabs-2026-06-30/report.json`

## Executive Read

The shell is stable and the tab set is broadly understandable on desktop, but the non-layer project surfaces still feel like three internal tools placed next to the product workflow instead of one coherent project workspace. The biggest issue is not visual polish. It is hierarchy.

Right now the user has to keep translating:

1. Which tab is for doing work versus checking status?
2. Which controls matter now versus later?
3. What is summary, what is action, and what is advanced machinery?

`Workspace` is the strongest of the three because it at least reflects the product tree. `Analytics` is operationally useful but emotionally cold and over-expanded for low-data states. `Project Settings` is still too dense, and on mobile it is materially broken: the live pass measured `76px` of horizontal overflow.

## What Should Happen

These three tabs should behave like one support band around the layer flow:

- `Workspace` should answer: "What exists, what is selected, and what should I do next?"
- `Analytics` should answer: "Is the system healthy, and do I need to care right now?"
- `Project Settings` should answer: "How should this project behave, and what controls are safe to change?"

That means:

- the shell should make the active tab purpose obvious in one glance
- summary should come before controls
- advanced controls should stay collapsed until the user explicitly needs them
- empty or zero-data states should shrink, not expand
- mobile should preserve the same hierarchy without sideways overflow

## Cross-Tab Findings

### 1. The tab labels are clear visually but noisy semantically

The visible cards are better than generic tabs, but the accessible labels and the on-screen framing still stack multiple names together, such as `Controls / Project Settings / Settings, exports, ownership`. The product is still speaking in internal category layers rather than user jobs.

What should happen:

- Keep one primary label per tab.
- Keep the supporting phrase short and task-shaped.
- Use the hero card only to restate the job of the selected tab, not a second taxonomy.

Recommended labels:

- `Workspace` -> "Work on the product structure"
- `Analytics` -> "Check runtime health and recent activity"
- `Project Settings` -> "Control project behavior and outputs"

### 2. The shell repeats context too often

Each tab repeats the project title, state pills, hero title, tab card, panel title, and then another panel title inside the page. This is especially heavy in `Project Settings`, where the user sees `Manage project settings`, then `Project behavior`, then `Project settings`, then `Project Model Overrides`.

What should happen:

- Show the project header once.
- Let the selected tab card act as the tab context.
- Inside each tab, start with a compact summary strip and then the primary action area.
- Avoid nested headings that repeat the same concept with slightly different wording.

## Tab 1: Workspace

### What works

- The page has the clearest sense of place.
- `Map` versus `Table` is easy to understand.
- The right-side inspector helps connect list selection to project meaning.
- Desktop hierarchy is readable and does not overflow.

### Problems

1. The page is doing too many jobs at once.
   The user sees workspace mode, project stats, bulk actions, filters, selection, an inspector, and layer actions in a single first screen.

2. The primary next step is not clear.
   The tab says `Shape the product structure`, but the UI does not clearly point to whether the user should review pillars, add a pillar, inspect the brief, or change the selected branch.

3. The top summary cards are mildly redundant.
   `Layer 1 pillars`, `Layer 2 features`, `Child branches`, and `Current focus` sit above a table that already exposes the same structure.

### What should happen

- Keep `Workspace` as the operational home for Layers 0-2, but make the top of the page more directive.
- Replace the current stat-card row with a smaller "current branch" summary plus one recommended next action.
- Treat bulk actions as selection-dependent controls that stay visually secondary until rows are selected.
- Keep the inspector, but on desktop it should feel like a contextual side panel, not equal weight with the main workspace table.

### Recommended first slice

1. Add one explicit status line under the hero, such as `3 pillars ready for review. No Layer 2 features yet.`
2. Collapse the top stat row into a single compact summary bar.
3. Hide or mute `Keep`, `Prioritize`, and `Cut` until a row is selected.
4. Rename `Ask about brief` to something more action-shaped in this context, such as `Ask assistant about selection`.

## Tab 2: Analytics

### What works

- The operational purpose is immediately understandable.
- Health and diagnostics are in the right tab.
- The page uses consistent cards and clear action buttons.

### Problems

1. The zero-data state is too large.
   The page currently devotes a full analytics dashboard to `0 tokens across 0 model calls`, empty breakdown panels, an empty run inspector, and an empty queue. It reads like a dead admin screen rather than a healthy quiet system.

2. Too much is expanded by default.
   Diagnostics options, privacy controls, queue state, breakdowns, and run inspection all occupy the first screen, even when no data exists.

3. The page does not separate everyday reassurance from specialist tooling.
   A normal user mostly needs to know `is the stack healthy?` and `did anything fail?` The rest should follow only if they choose to inspect deeper.

### What should happen

- Turn the top of `Analytics` into a compact status dashboard first.
- Collapse low-value empty sections.
- Show a healthy quiet state when there are no calls instead of rendering the full instrument panel at maximum size.

### Recommended structure

1. Health summary
   - Database
   - Model server
   - Jobs
   - Last failure, if any

2. Recent activity
   - recent calls if present
   - recent jobs if present
   - otherwise a compact `No recent activity` state

3. Advanced tools
   - Diagnostics preview/export
   - Privacy retention controls
   - Full run inspector

### Recommended first slice

1. Replace the huge zero-token hero with a smaller health-first banner when calls are zero.
2. Move `Privacy and retention` and `Diagnostics bundle` into collapsed advanced sections by default.
3. Hide empty `By layer`, `By model`, `By workflow`, and `Run inspector` panels until at least one run exists.

## Tab 3: Project Settings

### What works

- The summary strip at the top is directionally correct.
- Exports are now more clearly separated than in the earlier mixed tab.
- The sticky-ish save row is better than the older detached save button.

### Problems

1. The page is still too tall and too technical.
   The user moves from a good summary into a long implementation-driven form with compute mode, routing, profiles, embeddings, assignments, exports, competitive controls, and diagnostics memory.

2. The middle of the page still speaks architecture.
   `Project Model Overrides`, `LLM Profiles`, `Embedding Profiles`, and `Assignments` are valid concepts, but they are not the default mental model for most users trying to change how a project behaves.

3. Competitive intelligence appears twice.
   One section controls the project-level switch. Another controls competitor inputs and research mode. That is logically fine, but the page makes them feel duplicated instead of nested.

4. Mobile is currently broken.
   The live pass recorded horizontal overflow on mobile, and the screenshot shows the shell narrowing into a dense vertical tunnel while preserving wide control groups.

### What should happen

`Project Settings` should become a three-level experience:

1. Behavior summary
   - compute mode
   - assistant/generation/research routing
   - competitive intelligence on or off

2. Common controls
   - choose compute mode
   - choose whether competitive intelligence is enabled
   - save project behavior

3. Advanced controls
   - routing overrides
   - profiles
   - assignments
   - raw diagnostics/generation memory

Exports should be peer-level utility cards, not buried in the middle of configuration.

Competitive research configuration should sit under a single expandable `Competitive intelligence setup` section that only fully opens when the master switch is on.

### Recommended first slice

1. Fix mobile overflow first.
   This is a correctness issue, not a preference.
2. Move profile, embedding, and assignment editors under one collapsed `Advanced model setup` section.
3. Merge the two competitive-intelligence regions into one parent section with:
   - master switch
   - known competitors
   - research mode
   - matrix state
4. Keep `Diagnostics and generation memory` collapsed and visually deemphasized.

## Priority Order

1. Fix mobile `Project Settings` overflow and reduce horizontal pressure.
2. Simplify `Project Settings` into summary, common controls, and advanced controls.
3. Convert `Analytics` from an always-expanded dashboard into a health-first status page.
4. Tighten `Workspace` so the next recommended action is more obvious.
5. Reduce shell-level naming repetition across all three tabs.

## Recommended Product Rule

The non-layer tabs should feel like support surfaces around the product-building flow, not separate admin tools. If a user opens one of these tabs, the page should help them answer one question quickly, then stay out of the way.
