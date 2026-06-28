# Contributing to Strata

Thank you for helping improve Strata.

## Contribution license

By submitting a contribution, you agree that it may be distributed under the
same license as the project: the GNU Affero General Public License v3.0.
No separate contributor license agreement is required.

## Development setup

1. Install Python 3.12+, Node.js 22+, and PostgreSQL 16+ with pgvector.
2. Copy `.env.example` to `.env`.
3. Create a virtual environment and install `requirements-dev.txt`.
4. Run `npm ci` in `frontend/`.
5. Run the backend tests and frontend build before submitting changes.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_core.py -q
.\.venv\Scripts\python.exe -m compileall strata
cd frontend
npm run test:cache
npm run build
```

Keep source files below 1,000 lines and add focused tests for behavior changes.
Do not commit `.env`, model files, database files, logs, diagnostics exports, or
private project data.
