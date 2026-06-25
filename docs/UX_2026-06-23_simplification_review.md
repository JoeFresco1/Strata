# Strata UX Simplification Review

Date: 2026-06-23
Scope: Live localhost review of the current Strata UI
Environment: `http://127.0.0.1:5173` against the local API on `http://127.0.0.1:8000`
Method: Local Playwright pass with saved screenshots and text captures in `.tmp-playwright/ux-audit/` and `.tmp-playwright/ux-audit-interactions/`

## Overall Take

The product is capable, but the UI often leads with system power instead of user momentum.

The recurring pattern is not "broken UX." It is "too much UI at once." Screens tend to expose every layer, every setting, every future action, and every diagnostic surface at peer level. That makes the platform feel heavier than it needs to, even when the underlying behavior is reasonable.

If the goal is simple, elegant, and easy, the next pass should reduce visible options, shorten the number of concepts shown per screen, and make the default state answer one question clearly:

`What should I do next?`

## What Already Feels Good

- The visual style is clean and restrained. It does not feel chaotic in color, spacing, or typography.
- Export feedback is now materially better. After clicking `Create Full Project Export`, the page clearly shows success and file paths.
- The project library cards are readable and the `published`/`draft` badges help.

## Highest-Value Simplification Opportunities

### 1. Too many peer-level navigation choices in the project shell

- Surface: Project header tab row
- Evidence: `Layer 0`, `Generate`, `Review`, `Competitive Intelligence`, `Tree`, `Specs`, `Settings`, `Export`, plus `Assistant`
- Why it feels heavy:
  - The interface presents workflow steps, analysis views, admin/configuration, and utility actions as equal siblings.
  - A new or returning user has to decide between too many nouns before the product has re-established context.
- Simpler direction:
  - Reduce the top-level project shell to a smaller set of primary modes.
  - Good candidates:
    - `Brief`
    - `Build`
    - `Map`
    - `Project`
  - Move `Settings`, `Export`, and advanced assistant controls under `Project`.
  - Fold `Generate`, `Review`, and `Competitive Intelligence` into a single `Build` workspace with contextual sections.

### 2. The product often shows future-state controls before the current state is resolved

- Surface: `Generate`
- Evidence:
  - Layer 1 controls are visible.
  - Layer 2 controls are also visible but disabled by project state.
  - Layer 3 controls are visible even though there is no eligible Layer 3 work yet.
- Why it feels heavy:
  - The user is forced to parse downstream capabilities that are not actionable yet.
  - Disabled future sections read like admin scaffolding rather than a guided workflow.
- Simpler direction:
  - Show only the next actionable generation step by default.
  - Replace downstream disabled sections with one compact status card:
    - `Layer 2 unlocks after you keep or prioritize a Layer 1 pillar.`
  - Reveal deeper controls only after prerequisites are met or the user explicitly expands `Show later stages`.

### 3. Layer 0 is still doing too many jobs on one screen

- Surface: Published `Layer 0`
- Evidence:
  - Plan conversation
  - Published brief snapshot
  - What to cover next
  - Published-state badge and footer
  - Research status
  - Layer 0 market evidence dump
- Why it feels heavy:
  - The page mixes planning, published summary, workflow state, job history, and research output in one long scroll.
  - On a published brief, the large message box visually implies "keep editing here" even though the page is also trying to communicate a stable published state.
- Simpler direction:
  - Make published Layer 0 a summary-first screen.
  - Default layout:
    - brief summary
    - status
    - one primary next action
  - Move research status and raw market findings behind collapsible sections.
  - Change the revision flow from an always-open chat box to an explicit action like `Start revised draft`.

### 4. Review is valuable but too dense per pillar

- Surface: `Review`
- Evidence:
  - Every pillar card includes title, description, status, priority, score labels, competitor coverage, implementation profile tiles, and a competitor table.
- Why it feels heavy:
  - The user must visually re-read the same structure three times before deciding anything.
  - High-signal decisions are buried inside repeated low-level detail.
- Simpler direction:
  - Make the default review surface compact and decision-first.
  - Suggested structure:
    - one row per pillar
    - quality/status/priority at row level
    - `Expand details` for profile tiles and competitor evidence
  - Put the detailed implementation profile behind disclosure instead of front-loading it on every item.

### 5. The settings page exposes internal orchestration complexity too early

- Surface: `Settings`
- Evidence:
  - Profiles, embedding models, layer assignments, assistant orchestration, assistant synthesis, compaction, specialists, retrieval
- Why it feels heavy:
  - Most users do not need to think in terms of orchestration roles during ordinary project work.
  - The page reads like a system control panel instead of a project settings view.
- Simpler direction:
  - Default to a simple settings mode.
  - Keep only the settings most users actually need in normal use:
    - main model
    - embeddings
    - maybe per-layer overrides
  - Move the rest into an `Advanced runtime and assistant settings` section.
  - Consider hiding assistant sub-role settings unless `Advanced` is enabled.

### 6. Competitive Intelligence looks empty in a way that feels unfinished

- Surface: `Competitive Intelligence`
- Evidence:
  - The matrix shows headers but no populated rows.
  - The page has controls, but weak explanation of why the matrix is blank right now.
- Why it feels heavy:
  - It looks like the product has a feature surface ready before it has a meaningful result to show.
  - A blank matrix reads as absence or failure, not staged progress.
- Simpler direction:
  - Treat the empty state as a guided setup/result state, not as an empty table.
  - Example:
    - `No Layer 2 feature rows yet.`
    - `Generate or add Layer 2 features first, then run competitor research.`
  - Only render the full matrix once there is enough data for it to feel useful.

### 7. Tree is strong, but too many controls compete with the map

- Surface: `Tree`
- Evidence:
  - search, filters, view modes, zoom, reset, stats, layer cards, map canvas, full detail panel
- Why it feels heavy:
  - The canvas is the hero, but several control groups compete for attention before the user even reads the map.
  - The right-side detail panel is always expensive in screen real estate.
- Simpler direction:
  - Make the map the default hero.
  - Collapse stats into one compact strip.
  - Turn the detail panel into on-demand inspect mode instead of always-open.
  - Keep advanced controls under a single `View options` drawer.

### 8. The assistant drawer adds another layer of choice before giving value

- Surface: `Assistant`
- Evidence:
  - Conversation selector, scope selector, `Thinking`, `Deep`, empty canvas, input box
- Why it feels heavy:
  - The drawer asks the user to configure the assistant before the assistant has helped with anything.
  - It introduces meta-controls instead of a simple first interaction.
- Simpler direction:
  - Start with one obvious text box and 2-3 suggested prompts.
  - Hide `Scope`, `Thinking`, and `Deep` behind an `Advanced` affordance or infer them automatically until the user wants more control.
  - Let the first useful answer earn the right to show deeper controls.

### 9. Export is cleaner now, but diagnostics still sit too close to the main workflow

- Surface: `Export`
- Evidence:
  - Main export actions share the screen with `Diagnostics and generation memory`
- Why it feels heavy:
  - The export workflow itself is simple.
  - Debug and memory payloads are still adjacent to a user-facing utility flow.
- Simpler direction:
  - Keep export narrowly about export.
  - Move diagnostics to a separate debug surface, or keep them deeply collapsed under an explicit advanced label.

### 10. The project library still needs stronger differentiation between similar projects

- Surface: Project Library
- Evidence:
  - Many near-identical `Embedding Smoke` cards
- Why it feels heavy:
  - The cards are readable, but scanning still requires more effort than it should when names repeat.
- Simpler direction:
  - Strengthen secondary identity:
    - larger updated-at emphasis
    - stronger subtitle treatment
    - status + freshness grouped together
  - Add search sooner rather than later if the library is expected to grow.

## Product-Level Recommendation

If we want the UX to feel less overcomplicated, the most important shift is this:

Design each screen around the next decision, not around total system capability.

Right now the app often says:

`Here is everything this layer can do.`

It should more often say:

`Here is where you are, here is what is ready, and here is the one next move that matters.`

## Suggested Priority Order

1. Simplify project-level navigation.
2. Make `Generate` and `Layer 0` more state-aware and progressively disclosed.
3. Collapse `Settings` into simple vs advanced.
4. Make `Review` more compact and decision-first.
5. Reduce always-visible controls in `Tree` and `Assistant`.

