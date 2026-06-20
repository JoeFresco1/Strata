$ErrorActionPreference = "Stop"

# Start or initialize the repo-local PostgreSQL cluster used by Strata.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$localDir = Join-Path $root ".local"
$dataDir = Join-Path $localDir "postgres-data"
$logFile = Join-Path $localDir "postgres.log"
$pgBin = if ($env:SPECFORGE_PG_BIN) { $env:SPECFORGE_PG_BIN } else { "C:\Program Files\PostgreSQL\18\bin" }
$initDb = Join-Path $pgBin "initdb.exe"
$pgCtl = Join-Path $pgBin "pg_ctl.exe"
$pgIsReady = Join-Path $pgBin "pg_isready.exe"

New-Item -ItemType Directory -Path $localDir -Force | Out-Null

if (-not (Test-Path $initDb) -or -not (Test-Path $pgCtl) -or -not (Test-Path $pgIsReady)) {
    throw "PostgreSQL binaries not found under $pgBin"
}

$databaseUrl = if ($env:SPECFORGE_DATABASE_URL) { $env:SPECFORGE_DATABASE_URL } else { "postgresql://postgres@127.0.0.1:55433/specforge" }
$databaseUri = [System.Uri]$databaseUrl
$port = if ($databaseUri.Port -gt 0) { $databaseUri.Port } else { 55433 }

if (-not (Test-Path $dataDir)) {
    & $initDb -D $dataDir -U postgres -A trust -E UTF8 | Out-Null
}

& $pgIsReady -h 127.0.0.1 -p $port -d postgres | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $pgCtl -D $dataDir -l $logFile -o "-p $port" start | Out-Null
    $deadline = (Get-Date).AddMinutes(2)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        & $pgIsReady -h 127.0.0.1 -p $port -d postgres | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw "Local PostgreSQL did not become ready on port $port. Check $logFile"
    }
}

Write-Host "Strata local PostgreSQL is running on port $port"
