# Layers UX

## Layer 1

- Added a stronger stage shell above the project tabs so the workspace reads as an intentional Layer 1 and Layer 2 operating area instead of a flat tab strip.
- Added workspace signal cards for pillar count, feature count, current focus, and child branches so the Layer 1 tree state is legible before opening the inspector.
- Tightened the visual hierarchy in the project layer navigation with clearer kickers, denser labels, and more deliberate active-state treatment.

## Layer 2

- Added an active-feature summary strip above the Layer 2 workbench so the selected capability, owner pillar, research score, evidence count, and Layer 3 readiness stay visible while reviewing rows.
- Added a filter-specific empty state for the Layer 2 table so the workbench does not collapse into a confusing blank area when search and review filters exclude every feature.
- Kept the existing bulk-action and mobile-card improvements, but anchored them to a clearer top-level workbench context so the surface feels less like a raw table and more like an operator panel.

## Layer 3

- Added Layer 3 overview cards for total cards, cards needing review, unresolved decisions, and stale analyses so review pressure is visible before opening a single card.
- Added per-card metadata blocks for parent pillar, relationship count, open decisions, and citation count to make the selected card feel inspectable at a glance.
- Split the Layer 3 action wall into grouped save, analysis, and review controls so the editor reads cleanly and approval actions are easier to scan.

## Project Shell

- Swapped the older flat tab treatment for stage cards with short explanations, plus a current-stage summary panel above the tabs.
- Removed the purple-toned page accent from the project background in favor of a warmer secondary wash that fits the existing Strata palette better.
- Moved the typography to a crisper Windows-friendly stack built around `Aptos` and `Segoe UI Variable` when available.

## Project Workspace

- Replaced the stacked `next step` panel plus separate stat-card row with one tighter workspace overview band that combines recommendation, current workspace state, and readiness counts.
- Shifted the project workspace top from passive metrics toward directional context, so the user sees what is selected, what is ready, and what should happen next before hitting the map or table.
- Softened the map shell from `dashboard` language into `product map` language and added a compact focus card in the map header so the central canvas feels like a working surface rather than a reporting panel.
- Tightened table mode into a branch-review surface with a current-branch spotlight, visible/scope/selection chips, a clear-filters action, and an explicit empty state when filters narrow the table to zero rows.
