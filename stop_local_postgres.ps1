$ErrorActionPreference = "SilentlyContinue"

# Stop the repo-local PostgreSQL cluster when it is running.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dataDir = Join-Path (Join-Path $root ".local") "postgres-data"
$pgBin = if ($env:SPECFORGE_PG_BIN) { $env:SPECFORGE_PG_BIN } else { "C:\Program Files\PostgreSQL\18\bin" }
$pgCtl = Join-Path $pgBin "pg_ctl.exe"

if ((Test-Path $pgCtl) -and (Test-Path $dataDir)) {
    & $pgCtl -D $dataDir -m fast stop | Out-Null
}

Write-Host "Strata local PostgreSQL stop command sent."
