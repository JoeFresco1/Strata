# Strata Release QA Matrix Evidence

Date: 2026-06-28

Status: native disposable release matrix passed on this machine; Docker evidence and native PostgreSQL backup/restore evidence are still required before the completion-audit blocker can be closed.

## Native evidence

- Evidence bundle: `C:\Users\Fresc\Feature_gen\.runtime\release-qa\20260628-082739`
- Setup report: passed fresh first-run setup, post-setup library landing, and real project creation through the UI.
- API lifecycle report: passed restart recovery to `interrupted`, queued cancel, interrupted retry, cancelled retry, archive export/import, lifecycle warning capture, archived read-only enforcement, and unarchive recovery.
- Surface report: passed desktop and 390 px mobile library/workspace checks with zero horizontal overflow, zero unlabeled visible buttons, zero console errors, zero page errors, zero failed requests, and zero HTTP errors.
- Export evidence: created a diagnostics bundle and portable project archive under the disposable exports directory, and exercised full project export plus archive-export and Spec Kit handoff actions from the UI.

## What landed

- Added a reusable release QA matrix and closure criteria in `docs/RELEASE_QA_MATRIX.md`.
- Added a disposable native runner in `scripts/run_release_qa_native.ps1`.
- Added browser setup and surface audits under `.tmp-playwright/`.
- Added API lifecycle checks for restart recovery, cancel/retry, archive export/import, and archive read-only semantics.
- Added regression coverage for archive import warnings, archived-project write protection, and provider-readiness-aware test fixtures.

## Current blocker state

Item 8 in `docs/PLATFORM_COMPLETION_AUDIT.md` remains open until:

- one fresh native run includes PostgreSQL backup and restore proof;
- one fresh Docker run passes on a Docker-capable environment;
- the dated evidence report includes those remaining transcripts alongside the native disposable bundle above.
