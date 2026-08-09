# Strata QA Notes: Broken Or Misleading Features

Date: 2026-08-09

Scope: Post-merge browser and API QA on current `main` across the current product workflow

Environment: Production frontend served from `http://127.0.0.1:8010` against an isolated disposable SQLite database

Method: Browser traversal plus console, network, HTTP, API, and server-log inspection. No product fixes applied.

## Result: no confirmed deterministic product regression

The exercised non-model workflow completed without a confirmed broken or misleading product feature:

- 52 browser assertions passed.
- Browser diagnostics recorded zero console errors, page errors, failed requests, and HTTP 4xx/5xx responses.
- Server logs contained no application traceback or error response during the pass.
- The Project Library returned the disposable project with correct published lifecycle metadata.
- Map and all available workflow tabs opened successfully.
- Analytics, Project Settings, Create Project, and Assistant surfaces opened successfully.
- API health accurately reported that the configured model provider was unavailable; the UI repeated that state in the expanded runtime menu.

## Verification limitations

### Model-backed actions were not executed

The configured llama.cpp provider was offline, so this pass did not claim end-to-end verification of generation, research, overlap critics, Product Discovery, or assistant responses. The unavailable provider was treated as an environment limitation because both the health API and expanded runtime menu reported it honestly.

### Export mutations were not executed

Export screens and controls were inspected, but file-producing export actions were not invoked during this record-only pass. Their rendering and accessibility checks passed; output creation was not re-verified here.

### The old local fixture helper is stale, but it is not repository-shipped code

The ignored local helper `.tmp-playwright/seed_release_qa_fixture.py` created the Layer 0-2 fixture successfully, then failed when it called the removed `Database.upsert_layer3_card` method. The helper lives under a gitignored directory and does not affect the GitHub repository or application runtime. This should be repaired or discarded before it is reused for future local QA, but it is not logged as a product defect.

## Evidence

- Machine-readable report: `.runtime/postmerge-qa-20260809-1540/evidence/report.json`
- Desktop and mobile screenshots/text captures: `.runtime/postmerge-qa-20260809-1540/evidence/`
- Isolated API logs: `.runtime/postmerge-qa-20260809-1540/api.stdout.log` and `.runtime/postmerge-qa-20260809-1540/api.stderr.log`
