# Strata QA Notes: Broken Or Misleading Features

Date: 2026-06-21
Scope: Localhost QA pass across Layer 0, Layer 1, and Layer 2
Environment: `http://127.0.0.1:5173` with local API on `http://127.0.0.1:8000`
Method: Browser-based manual pass only. No fixes applied.

## 1. Layer 0 Plan conversation can duplicate prior messages

- Surface: Draft project `idea for survey platform` on `Layer 0` > `Plan`
- Repro:
  1. Open the draft project.
  2. Review the visible conversation history.
- Observed:
  - The same user message and assistant reply appeared twice in the transcript.
- Impact:
  - The conversation history becomes untrustworthy.
  - It looks like the system repeated work or saved state twice.

## 2. Competitive Intelligence does not inherit known competitors from the project brief

- Surface: Published project `Deep Research Smoke 2026-06-17`
- Repro:
  1. Open `Layer 0` and confirm the brief includes competitors such as `Gainsight` and `Totango`.
  2. Open `Competitive Intelligence`.
- Observed:
  - The Competitive Intelligence `Known Competitors` field is empty.
  - The page asks the user to add competitors manually.
  - API snapshot for the same project shows `competitive_settings.known_competitors` as an empty array.
- Impact:
  - The manual competitive workflow is disconnected from the already-published brief.
  - Users can reasonably assume their data was lost or ignored.

## 3. Layer 1 competitor coverage is inconsistent across pillars

- Surface: Published project `Deep Research Smoke 2026-06-17` on `Review`
- Repro:
  1. Open `Review`.
  2. Compare the three Layer 1 pillars.
- Observed:
  - `Predictive Retention Intelligence` shows competitor coverage rows.
  - `Prescriptive Retention Intelligence` and `Unified Commercial Operations` show `No pillar research finding yet.`
  - At the same time, the Layer 0 `Research Status` section shows completed Layer 1 jobs.
  - API data contains zero-row `pillar_coverage_matrix` findings for those two pillars.
- Impact:
  - The UI gives the impression that research is missing, while backend records suggest the jobs completed.
  - Users cannot tell whether the feature failed, returned zero evidence, or simply rendered poorly.

## 4. Publish-state handling is misleading enough to look functionally wrong

- Surface: Published project `Deep Research Smoke 2026-06-17` on `Layer 0`
- Repro:
  1. Open the published project.
  2. Review the state copy and CTA area.
- Observed:
  - Draft-only language remains visible.
  - `Publish to Layer 1` remains available on an already-published brief.
- Impact:
  - Even if the backend state is correct, the frontend presents an invalid workflow.
  - Users may click a publish action they should no longer need or even see.

## 5. Export behavior is discoverable only through filesystem side effects

- Surface: Published project `Deep Research Smoke 2026-06-17` on `Export`
- Repro:
  1. Click `Export Markdown and JSON`.
  2. Watch the browser for a download or a success message.
  3. Check the repo `exports/` folder.
- Observed:
  - No visible success confirmation appeared in the app.
  - No browser download fired.
  - Files were created in `exports/`.
- Impact:
  - Users can easily conclude the export failed.
  - The feature works at the storage layer but feels broken in the interface.
