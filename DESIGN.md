---
name: Strata
description: Local-first product discovery and feature architecture workspace.
colors:
  primary: "#245f73"
  primary-strong: "#1e6d85"
  secondary: "#6d5bd0"
  ink: "#172026"
  muted-ink: "#4e5f65"
  app-bg: "#f3f6f8"
  panel-bg: "#ffffff"
  panel-soft: "#f7fafb"
  surface-alt: "#eef3f6"
  border: "#d9e0e6"
  success-bg: "#dff2e8"
  success-ink: "#145a36"
  warning-bg: "#fff3d6"
  warning-ink: "#7a4d00"
  error-bg: "#fff0f1"
  error-ink: "#8d2430"
typography:
  display:
    fontFamily: "\"Segoe UI\", \"Helvetica Neue\", sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.2
  headline:
    fontFamily: "\"Segoe UI\", \"Helvetica Neue\", sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: "\"Segoe UI\", \"Helvetica Neue\", sans-serif"
    fontSize: "1rem"
    fontWeight: 700
    lineHeight: 1.35
  body:
    fontFamily: "\"Segoe UI\", \"Helvetica Neue\", sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "\"Segoe UI\", \"Helvetica Neue\", sans-serif"
    fontSize: "0.88rem"
    fontWeight: 600
    lineHeight: 1.35
  mono:
    fontFamily: "ui-monospace, \"SFMono-Regular\", Consolas, monospace"
    fontSize: "0.92rem"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  xs: "6px"
  sm: "8px"
  md: "12px"
  surface: "14px"
  lg: "16px"
  xl: "18px"
  section: "20px"
  modal: "24px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "0.72rem 1rem"
  button-secondary:
    backgroundColor: "{colors.surface-alt}"
    textColor: "#1f3b46"
    rounded: "{rounded.sm}"
    padding: "0.72rem 1rem"
  input-default:
    backgroundColor: "{colors.panel-bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0.8rem"
  panel-default:
    backgroundColor: "{colors.panel-bg}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "1rem"
  status-pill:
    backgroundColor: "{colors.surface-alt}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.22rem 0.5rem"
---

# Design System: Strata

## Overview

**Creative North Star: "The Calm Control Room"**

Strata is a working product tool, not a brand showcase. The interface should feel like a dependable control room for shaping product architecture: quiet, legible, and ready for sustained task work. The codebase already expresses that through cool slate surfaces, teal action color, restrained plum accents, familiar form controls, and consistent rounded geometry that stays soft without becoming playful.

This system rejects novelty-for-novelty's-sake. It uses light gradients and shadow only to separate work zones, loading states, overlays, and navigation rails. It does not ask the user to admire the UI. It should help them move from project library to brief, workspace, specs, and settings with minimal translation cost.

**Key Characteristics:**
- Familiar sans-serif product typography with a tight hierarchy.
- Cool neutral surfaces with teal reserved for action and focus.
- Rounded panels and pills that soften density without looking decorative.
- Motion used for feedback, reveal, and loading only.
- Dense information presented in calm, segmented containers.

## Colors

The palette is a restrained product palette: cool paper neutrals, one trustworthy teal, and a limited plum accent for emphasis and selected-state contrast.

### Primary
- **Workspace Teal** (`#245f73`): The canonical action color for primary buttons, active segmented controls, link-style actions, spinner heads, and major task confirmation moments.
- **Resolved Teal** (`#1e6d85`): The stronger teal used for selected execution options and moments that need firmer active-state emphasis than the base action color.

### Secondary
- **Signal Plum** (`#6d5bd0`): A limited accent used in radial background atmosphere and selected-row or selected-card treatments. It is a supporting note, not a second action system.

### Neutral
- **Control Ink** (`#172026`): Primary text, headings, and high-importance labels.
- **Support Ink** (`#4e5f65`): Secondary descriptions, metadata, and long-form support copy.
- **Cool Canvas** (`#f3f6f8`): The app-level working background.
- **Paper Surface** (`#ffffff`): Primary panel, modal, input, card, and drawer surface.
- **Mist Surface** (`#f7fafb`): Secondary contained surfaces such as guide cards, empty states, and advanced option groups.
- **Utility Surface** (`#eef3f6`): Secondary buttons, tab rests, quiet pills, and low-emphasis controls.
- **Division Line** (`#d9e0e6`): Default border and separation color across panels, tables, tabs, and form fields.

### Named Rules
**The One Accent Rule.** Teal is the only true action color. Plum may support atmosphere or selection, but it must never compete with teal for primary intent.

**The Cool Neutrals Rule.** Neutrals stay cool and practical. Do not warm them into beige, cream, or editorial paper tones.

## Typography

**Display Font:** "Segoe UI", "Helvetica Neue", sans-serif
**Body Font:** "Segoe UI", "Helvetica Neue", sans-serif
**Label/Mono Font:** ui-monospace, "SFMono-Regular", Consolas, monospace for code-like editing zones only

**Character:** Typography is intentionally familiar. Strata uses a single UI family for speed, trust, and consistency, then switches to monospace only when the task becomes technical or code-adjacent.

### Hierarchy
- **Display** (700, `2rem`, `1.2`): Project and page-level headings. Used sparingly.
- **Headline** (700, `1.5rem`, `1.25`): Modal titles, section anchors, and key workspace headers.
- **Title** (700, `1rem`, `1.35`): Card headings, option titles, and compact panel labels.
- **Body** (400, `1rem`, `1.5`): Standard explanatory copy, field text, and workspace prose. Keep general reading blocks near `65ch-75ch` when prose grows beyond UI snippets.
- **Label** (600, `0.88rem`, `1.35`): Form labels, metadata, pills, summaries, and compact state text.

### Named Rules
**The No Performance Typography Rule.** No display fonts in labels, controls, settings, tables, or data-heavy views. If the user is working, the typography must disappear into the task.

## Elevation

Strata uses a hybrid depth model: flat borders do most of the structural work, while soft shadows add lift to actionable cards, floating rails, menus, and modal shells. Depth is always ambient rather than dramatic. Tonal layering carries most separation; shadows exist to confirm interaction or containment.

### Shadow Vocabulary
- **Surface Lift** (`0 10px 24px rgba(23, 32, 38, 0.07)`): Default project cards and higher-value contained surfaces.
- **Action Lift** (`0 8px 16px rgba(36, 95, 115, 0.18)`): Rail actions and emphatic interactive controls.
- **Overlay Lift** (`0 30px 70px rgba(16, 24, 28, 0.24)`): Modal shells and dominant overlays.
- **Edge Lift** (`-12px 0 32px rgb(24 39 49 / 16%)`): The assistant drawer's lateral separation shadow.

### Named Rules
**The Structural First Rule.** Borders and background shifts establish layout first. Shadows are a supporting layer, never the primary organizing principle.

**The State Lift Rule.** Heavier lift belongs to things the user can act on or things that temporarily sit above the workspace.

## Components

Every core component is meant to feel stable, efficient, and immediately legible.

### Buttons
- **Shape:** Soft utility rounding (`8px`) by default, with pill rounding (`999px`) reserved for chips and compact status surfaces.
- **Primary:** Workspace Teal (`#245f73`) background with white text, `0.72rem 1rem` padding, and no border.
- **Hover / Focus:** Hover uses subtle brightness or lift rather than color theatrics. Focus treatment should remain visible and high-contrast even where the current code relies mostly on hover.
- **Secondary / Ghost / Tertiary:** Secondary buttons use Utility Surface (`#eef3f6`) with darker teal-slate text and a thin border. Ghost buttons are text-led, borderless, and used for local navigation like "Back To Library" or dismissive actions.

### Chips
- **Style:** Pills use `999px` radius, light neutral backgrounds, compact spacing, and bold compact labels.
- **State:** Published or success-like states shift into green-tinted surfaces; passive states stay on Utility Surface.

### Cards / Containers
- **Corner Style:** Working cards range from `14px` to `18px`; larger shells go to `24px`.
- **Background:** Primary containers sit on Paper Surface (`#ffffff`) with slight cool gradients on more premium or denser modules.
- **Shadow Strategy:** Contained surfaces use Surface Lift; cards on hover may gain additional lift and a slightly stronger border.
- **Border:** Borders are thin, cool, and constant. Dashed borders are reserved for archived or lower-energy states.
- **Internal Padding:** Standard panels start at `1rem`; denser settings and decision rows often use `0.75rem` to `0.9rem`.

### Inputs / Fields
- **Style:** Inputs are full-width white fields with `8px` radius, a cool gray border, and generous interior padding (`0.8rem`).
- **Focus:** Active selections currently rely on border-color change and inset emphasis. Future additions must keep focus states more explicit, not subtler.
- **Error / Disabled:** Error states use warm warning or red surfaces with legible dark text. Disabled states lower opacity and pointer affordance without removing label clarity.

### Navigation
- **Style:** The app rail uses a high-clarity white-to-cool-neutral gradient with slim borders and generous spacing. When expanded, it becomes a compact command column rather than a decorative sidebar.
- **Default / Hover / Active:** Rail actions use teal gradients and consistent shadow. Tabs rest on low-contrast neutral surfaces and invert to darkened teal-slate when active.
- **Mobile Treatment:** Layout collapses structurally below tablet widths. Navigation loses ornamental positioning before typography or controls are compressed.

### Signature Component
- **Project Library Card:** This is the most representative Strata component. It combines a white elevated surface, subtle top-edge gradient signal, compact metadata, and a balanced action row. It should always read as "ready to continue work," never as marketing tile chrome.

## Do's and Don'ts

### Do:
- **Do** keep the path to the next action obvious through stable button placement, strong section headers, and compact explanatory copy.
- **Do** use familiar UI patterns and a single sans-serif family for the majority of the product surface.
- **Do** keep interactive targets spacious enough for quick scanning and repeated workflow use.
- **Do** preserve readable contrast with Control Ink (`#172026`) or Support Ink (`#4e5f65`) instead of airy low-contrast gray.
- **Do** keep motion short (`150ms-250ms`) and state-driven: loading, expanding, revealing, or confirming.

### Don't:
- **Don't** create **dense walls of text**. Break explanation into cards, summaries, lists, or scoped helper copy.
- **Don't** ship **cluttered layouts**. If a panel cannot explain itself quickly, reduce competing surfaces before adding more decoration.
- **Don't** introduce **confusing navigation** through custom affordances, inconsistent button styling, or hidden action placement.
- **Don't** use **slow loading animations** or choreographed page reveals. Loading should reassure, not delay.
- **Don't** add **overly complex instructions** when a label, helper sentence, or guided empty state would do the job.
- **Don't** add decorative motion that does not communicate state.
- **Don't** use heavy saturated accents on inactive controls, decorative glassmorphism, gradient text, or side-stripe borders.
