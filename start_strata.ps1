$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
Push-Location frontend
try {
    if (-not (Test-Path "node_modules")) { npm ci }
    npm run build
} finally {
    Pop-Location
}

& ".\.venv\Scripts\python.exe" run_strata.py
