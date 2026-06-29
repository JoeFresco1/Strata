# Strata Release QA Matrix

Date: 2026-06-28

Purpose: close the remaining end-to-end release QA blocker in `docs/PLATFORM_COMPLETION_AUDIT.md` with one repeatable matrix, one native evidence run, and one Docker evidence run.

## Environments

| Environment | Purpose | Required evidence | Runner |
| --- | --- | --- | --- |
| Native Windows disposable install | First-run setup, project creation, restart recovery, cancel/retry, archive import/export, desktop/mobile browser QA | JSON reports, screenshots, exported archive paths, API lifecycle report, final pass/fail summary | This machine via `scripts/run_release_qa_native.ps1` |
| Docker Compose disposable install | Packaging and setup parity for self-hosters | Startup transcript, first-run/setup proof, smoke-path report, archive/export proof, final pass/fail summary | Docker-capable host or CI runner |
| Native PostgreSQL backup/restore validation | Data ownership and restore viability | Backup command transcript, restore command transcript, post-restore project verification | Native host with `pg_dump` and `pg_restore` |

## Closure Criteria

The release QA blocker stays open until every item below has fresh dated evidence:

| Audit bullet | Closure requirement | Evidence source |
| --- | --- | --- |
| Fresh disposable install | Run against a clean disposable data directory and empty setup state | Native runner summary plus setup report |
| First-run setup | Complete `SetupWizard`, confirm post-save model health response, land in Project Library | Browser setup report and screenshots |
| Project creation through Layer 3 | Create a real project in UI, then verify a seeded Layer 3-ready fixture through workspace, analytics, project tools, and capability design surfaces | Browser setup report, browser surface report |
| Restart during active work | Restart with a seeded running durable job and verify startup recovery marks it `interrupted` and retryable | API lifecycle report |
| Cancel/retry paths | Cancel a queued durable job, retry an interrupted job, retry a cancelled job, and confirm completion where applicable | API lifecycle report |
| Backup/restore | Produce a PostgreSQL backup, restore into a clean target, reopen Strata, and confirm a real project is intact | Manual transcript attached to dated evidence report |
| Archive export/import | Export a portable project archive, import it as a new project, verify warnings and remapped identity, and confirm archive read-only behavior | API lifecycle report and browser surface report |
| Docker and native installation checks | Record one passing native run and one passing Docker run | Native summary plus Docker summary |
| Desktop and mobile browser QA | Run desktop and 390 px mobile audits with screenshots and console/network diagnostics | Browser surface report |

## Automated Assets

- `scripts/run_release_qa_native.ps1`
  Runs the disposable native matrix on this machine and writes an evidence bundle under `.runtime/release-qa/`.
- `.tmp-playwright/release_matrix_setup.mjs`
  Validates first-run setup and creates one disposable project through the real UI.
- `.tmp-playwright/seed_release_qa_fixture.py`
  Seeds a deeper Layer 3-ready fixture plus durable-job scenarios into the disposable database.
- `.tmp-playwright/release_matrix_api_checks.py`
  Verifies restart recovery, cancel/retry, archive export/import, and archive read-only semantics.
- `.tmp-playwright/release_matrix_surface_audit.mjs`
  Runs desktop and mobile browser checks against the seeded fixture and imported archive.

## Native Run Sequence

1. Stop any prior disposable release-QA app processes.
2. Build the production frontend so FastAPI serves the same-origin release surface.
3. Start Strata with disposable `STRATA_DB_PATH`, `STRATA_EXPORTS_DIR`, and `STRATA_PORT` values.
4. Run the browser setup script against the clean install.
5. Stop Strata, seed the disposable database with release fixture data and durable-job scenarios, then restart.
6. Run the API lifecycle checks.
7. Run the browser surface audit on desktop and mobile widths.
8. Review the generated summary JSON and copy the key results into a dated evidence report.

## Manual Additions Per Run

- Native PostgreSQL backup and restore transcript.
- Docker Compose run transcript from a Docker-capable host or CI runner.
- Any operator notes about environment-specific failures, skips, or delegated Docker verification.

## Evidence Bundle Layout

The native runner writes:

- `setup-report.json`
- `api-lifecycle-report.json`
- `surface-report.json`
- `summary.json`
- `screenshots/`
- `surface-text/`

All release evidence reports should link to these artifacts and explicitly call out any missing Docker or backup/restore proof.
