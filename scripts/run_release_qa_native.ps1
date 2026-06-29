param(
    [int]$Port = 8010,
    [string]$ModelUrl = "http://127.0.0.1:8080",
    [string]$ModelName = "",
    [string]$EvidenceRoot = ""
)

$ErrorActionPreference = "Stop"

function Wait-ForHttp {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -TimeoutSec 5 | Out-Null
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Timed out waiting for $Url"
}

function Stop-ReleaseQaProcess {
    param([string]$PidFile)
    if (Test-Path $PidFile) {
        $pidValue = Get-Content $PidFile | Select-Object -First 1
        if ($pidValue) {
            Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-ModelName {
    param([string]$BaseUrl)
    if ($ModelName) {
        return $ModelName
    }
    try {
        $models = Invoke-RestMethod -Uri "$($BaseUrl.TrimEnd('/'))/v1/models" -TimeoutSec 10
        $first = $models.data | Select-Object -First 1
        if ($first.id) {
            return [string]$first.id
        }
    } catch {
    }
    return "local-model"
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $root ".venv\Scripts\python.exe"
$evidenceBase = if ($EvidenceRoot) { $EvidenceRoot } else { Join-Path $root ".runtime\release-qa" }
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$evidenceDir = Join-Path $evidenceBase $timestamp
$screenshotsDir = Join-Path $evidenceDir "screenshots"
$textDir = Join-Path $evidenceDir "surface-text"
$dbPath = Join-Path $evidenceDir "release-qa.db"
$exportsDir = Join-Path $evidenceDir "exports"
$apiStdout = Join-Path $evidenceDir "api.stdout.log"
$apiStderr = Join-Path $evidenceDir "api.stderr.log"
$pidFile = Join-Path $evidenceDir "api.pid"
$frontendDir = Join-Path $root "frontend"
$resolvedModelName = Resolve-ModelName -BaseUrl $ModelUrl

if (-not (Test-Path $python)) {
    throw "Virtual environment missing at $python"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required to run the Playwright release QA helpers."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required to build the production frontend before release QA."
}

New-Item -ItemType Directory -Path $evidenceDir, $screenshotsDir, $textDir, $exportsDir -Force | Out-Null

Push-Location $frontendDir
try {
    npm run build
} finally {
    Pop-Location
}

function Start-ReleaseQaApp {
    Stop-ReleaseQaProcess -PidFile $pidFile
    $env:STRATA_DB_BACKEND = "sqlite"
    $env:STRATA_DB_PATH = $dbPath
    $env:STRATA_EXPORTS_DIR = $exportsDir
    $env:STRATA_PORT = [string]$Port
    $env:STRATA_EMBEDDINGS_ENABLED = "false"
    $env:LLAMA_BASE_URL = $ModelUrl
    $env:STRATA_MODEL_NAME = $resolvedModelName
    $process = Start-Process -FilePath $python -ArgumentList "-m uvicorn serve_api:app --host 127.0.0.1 --port $Port" -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $apiStdout -RedirectStandardError $apiStderr -PassThru
    Set-Content -Path $pidFile -Value $process.Id
    Wait-ForHttp -Url "http://127.0.0.1:$Port/api/health" -TimeoutSeconds 90
}

try {
    Start-ReleaseQaApp

    node (Join-Path $root ".tmp-playwright\release_matrix_setup.mjs") `
        --base-url "http://127.0.0.1:$Port" `
        --evidence-dir $evidenceDir `
        --model-url $ModelUrl `
        --model-name $resolvedModelName | Out-Null

    Stop-ReleaseQaProcess -PidFile $pidFile

    & $python (Join-Path $root ".tmp-playwright\seed_release_qa_fixture.py") --db-path $dbPath | Out-Null

    Start-ReleaseQaApp

    $apiReport = & $python (Join-Path $root ".tmp-playwright\release_matrix_api_checks.py") --api-base "http://127.0.0.1:$Port/api" --evidence-dir $evidenceDir --db-path $dbPath
    $apiReportPath = ($apiReport | Select-Object -Last 1).Trim()
    $apiPayload = Get-Content $apiReportPath -Raw | ConvertFrom-Json

    node (Join-Path $root ".tmp-playwright\release_matrix_surface_audit.mjs") `
        --base-url "http://127.0.0.1:$Port" `
        --evidence-dir $evidenceDir `
        --imported-project-name $apiPayload.imported_project_name | Out-Null

    $summary = [ordered]@{
        generated_at = (Get-Date).ToString("o")
        evidence_dir = $evidenceDir
        db_path = $dbPath
        exports_dir = $exportsDir
        setup_report = (Join-Path $evidenceDir "setup-report.json")
        api_lifecycle_report = $apiReportPath
        surface_report = (Join-Path $evidenceDir "surface-report.json")
        backup_restore_status = "manual follow-up required"
        docker_status = "external Docker-capable runner required"
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $evidenceDir "summary.json")
    Write-Host "Release QA evidence written to $evidenceDir"
} finally {
    Stop-ReleaseQaProcess -PidFile $pidFile
}
