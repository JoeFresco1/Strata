# Strata Full-Platform Playwright QA

Date: 2026-06-24  
Scope: Live localhost interaction and UX audit across the project library, Layer 0, the Layer 0-2 living workspace, Layer 2 competitive intelligence, Capability Design, project settings/export, and the project assistant.

## Environment

- Frontend: `http://127.0.0.1:5173`
- Primary API: `http://127.0.0.1:8000`
- Local model server: `http://127.0.0.1:8080`
- Full-depth fixture: isolated SQLite API temporarily served on port `8001`; stopped and removed after QA.
- Browser: Playwright Core 1.61 with local Microsoft Edge.

## Defects Found And Fixed

1. React hook-order crash during bootstrap
   - `App` returned its loading screen before two `useMemo` hooks, then called those hooks after config loaded.
   - React aborted the library render with `Rendered more hooks than during the previous render`.
   - Fixed by moving all hooks above conditional returns.

2. Mobile project-library overflow
   - The library header was 84 px wider than a 390 px viewport.
   - Fixed by stacking the header and making its action controls full width below 720 px.

3. Missing favicon
   - Every browser load emitted a 404 for `/favicon.ico`.
   - Added and linked a local SVG favicon.

4. Plain competitor names treated as URLs
   - `Culture Amp` rendered as `Culture%20amp` in the Layer 2 competitor matrix.
   - Fixed competitor labeling so only URL/domain-shaped values are parsed as hostnames.

5. Codex browser-host startup regression
   - The configured Node browser host was launched without the runtime's supported `--disable-sandbox` argument, causing `codex/sandbox-state-meta: missing field 'sandboxPolicy'`.
   - Restored `args = ["--disable-sandbox"]` in `C:\Users\Fresc\.codex\config.toml`.
   - New browser-host processes will use the corrected startup mode.

## Playwright Coverage

- Open/collapse navigation.
- Open and close Guide, System Prompts, and Settings.
- Validate create-project required fields and cancellation without creating data.
- Change library sort order.
- Open published and draft projects.
- Switch Workspace Map/Table views.
- Switch Layer 0 Plan/Form modes and validate composer enablement.
- Open Capability Design and verify full-depth card rendering.
- Validate unsaved-card discard protection.
- Run approved Capability Design export against the disposable fixture.
- Open project export, create a full project export, and verify visible output paths.
- Open competitive intelligence and verify inherited competitors and matrix labels.
- Open and close the project assistant.
- Return to the library.
- Verify desktop and 390 px mobile layouts for horizontal overflow.
- Check visible buttons for accessible labels.
- Capture console errors, page errors, failed requests, and HTTP responses at or above 400.

Generation, research, review-state mutations, and assistant sends were not blindly triggered across real projects because they are expensive or alter durable user data. Their controls, enabled/disabled gating, and surrounding UX were inspected; full-depth data mutations were limited to an isolated disposable fixture.

## Final Results

- Playwright checks: 87 passed, 0 defects
- Browser console errors: 0
- Page errors: 0
- Failed requests: 0
- HTTP errors: 0
- Backend tests: 85 passed
- Python compile: passed
- Frontend production build: passed
- Model API, FastAPI health, and frontend HTTP checks: passed

Detailed machine-readable evidence and screenshots are in `.tmp-playwright/full-platform-qa/`.
