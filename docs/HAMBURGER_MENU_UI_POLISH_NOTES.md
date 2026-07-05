# Hamburger Menu UI Polish Notes

Date: 2026-06-30
Repo: `C:\Users\Fresc\Feature_gen`

## Scope

This pass focused on the pages opened from the main hamburger rail:

- `Guide`
- `System Prompts`
- `App Settings`

It also polished the hamburger rail itself so those pages feel like intentional destinations rather than plain utility buttons.

## Hamburger Rail

- Reworked the rail actions from simple text buttons into descriptive cards with a label plus short helper copy.
- Added a small runtime status card under the rail actions so the sidebar carries useful context instead of raw footer text.
- Kept the menu compact while making each destination easier to scan before opening it.

## Guide

- Added a stronger hero section that explains the intended product flow from Layer 0 through delivery and diagnostics.
- Added quick-start pills so the workflow order is visible at a glance.
- Added a `Common jobs` section that routes common user intents to the right surface faster.
- Added side guidance that clarifies when to use `System Prompts` versus `App Settings`.
- Converted guide sections into more structured cards with numbered badges and a `when to use this` sentence on every card.
- Upgraded the visual hierarchy so the guide reads more like a product map and less like a flat wall of text.

## System Prompts

- Tightened the modal subtitle so it is clearer that edits affect future projects rather than existing snapshots.
- Added a summary strip at the top showing prompt count, group count, and scope.
- Added editing-guidance cards so the page explains how prompt changes propagate before the user starts editing.
- Kept the existing grouped editor intact, but made the page feel more like a managed catalog and less like a raw form dump.

## App Settings

- Added a top-level overview panel before the dense settings editor.
- Surfaced reusable high-level context: LLM profile count, embedding profile count, assignment count, and provider readiness.
- Added an operating-model section that distinguishes app-wide defaults from per-project overrides.
- Reframed the page as the place where new-project defaults are defined, which should reduce confusion with per-project overrides.

## Verification

- Frontend build passed with `npm run build` from `frontend/`.
- Local API health returned `ok: true` from `http://127.0.0.1:8000/api/health`.
- Frontend dev server was already listening on `http://127.0.0.1:5173`.
