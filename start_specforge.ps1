$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$runtimeDir = Join-Path $root ".runtime"
$logsDir = Join-Path $runtimeDir "logs"
$serverPidFile = Join-Path $runtimeDir "llama-server.pid"
$apiPidFile = Join-Path $runtimeDir "api.pid"
$frontendPidFile = Join-Path $runtimeDir "frontend.pid"
$serverStdout = Join-Path $logsDir "llama-server.stdout.log"
$serverStderr = Join-Path $logsDir "llama-server.stderr.log"
$apiStdout = Join-Path $logsDir "api.stdout.log"
$apiStderr = Join-Path $logsDir "api.stderr.log"
$frontendStdout = Join-Path $logsDir "frontend.stdout.log"
$frontendStderr = Join-Path $logsDir "frontend.stderr.log"
$frontendDir = Join-Path $root "frontend"

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment missing at $venvPython. Install dependencies first."
}
if (-not (Test-Path $frontendDir)) {
    throw "Frontend directory missing at $frontendDir"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is required to run the React localhost frontend."
}

powershell -ExecutionPolicy Bypass -File (Join-Path $root "start_local_postgres.ps1")

$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -match '^\s*$') {
            return
        }
        $parts = $_ -split '=', 2
        if ($parts.Count -eq 2) {
            [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
        }
    }
}

$serverExe = if ($env:LLAMA_SERVER_EXE) { $env:LLAMA_SERVER_EXE } else { "llama-server" }
$modelPath = $env:SPECFORGE_MODEL_PATH
$baseUrl = if ($env:LLAMA_BASE_URL) { $env:LLAMA_BASE_URL.TrimEnd('/') } else { "http://127.0.0.1:8080" }
$contextSize = if ($env:LLAMA_CONTEXT_SIZE) { $env:LLAMA_CONTEXT_SIZE } else { "32768" }
$gpuLayers = if ($env:LLAMA_GPU_LAYERS) { $env:LLAMA_GPU_LAYERS } else { "35" }
$modelAlias = if ($env:SPECFORGE_MODEL_NAME) { $env:SPECFORGE_MODEL_NAME } else { "qwen-27b-q3-no-thinking" }
$reasoningMode = if ($env:LLAMA_REASONING_MODE) { $env:LLAMA_REASONING_MODE } else { "off" }
$reasoningFormat = if ($env:LLAMA_REASONING_FORMAT) { $env:LLAMA_REASONING_FORMAT } else { "none" }
$reasoningBudget = if ($env:LLAMA_REASONING_BUDGET) { $env:LLAMA_REASONING_BUDGET } else { "0" }
$apiPort = if ($env:SPECFORGE_API_PORT) { $env:SPECFORGE_API_PORT } else { "8000" }
$frontendPort = if ($env:SPECFORGE_FRONTEND_PORT) { $env:SPECFORGE_FRONTEND_PORT } else { "5173" }

if (-not (Test-Path $serverExe)) {
    throw "llama-server executable not found at $serverExe"
}
if (-not (Test-Path $modelPath)) {
    $modelPath = & $venvPython -c "from specforge.config import AppConfig, resolve_model_path; print(resolve_model_path(AppConfig()) or '')"
}
if (-not $modelPath -or -not (Test-Path $modelPath)) {
    throw "GGUF model not found. Set SPECFORGE_MODEL_PATH or ensure auto-discovery can find a GGUF under the configured model root."
}

$healthOk = $false
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/v1/models" -TimeoutSec 5
    if ($response.data) {
        $healthOk = $true
    }
} catch {
    $healthOk = $false
}

if (-not $healthOk) {
    $serverArgs = @(
        "-m `"$modelPath`"",
        "-c $contextSize",
        "-ngl $gpuLayers",
        "--host 127.0.0.1",
        "--port 8080",
        "--reasoning $reasoningMode",
        "--reasoning-format $reasoningFormat",
        "--reasoning-budget $reasoningBudget",
        "--alias `"$modelAlias`"",
        "--jinja",
        "--no-ui"
    ) -join " "
    $serverProcess = Start-Process -FilePath $serverExe -ArgumentList $serverArgs -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr -PassThru
    Set-Content -Path $serverPidFile -Value $serverProcess.Id

    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        try {
            $response = Invoke-RestMethod -Uri "$baseUrl/v1/models" -TimeoutSec 10
            if ($response.data) {
                $healthOk = $true
                break
            }
        } catch {
        }
    }
}

if (-not $healthOk) {
    throw "llama.cpp server did not become healthy. Check $serverStderr and $serverStdout"
}

$apiOk = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$apiPort/api/health" -TimeoutSec 5 | Out-Null
    $apiOk = $true
} catch {
    $apiOk = $false
}

if (-not $apiOk) {
    $apiArgs = "-m uvicorn serve_api:app --host 127.0.0.1 --port $apiPort"
    $apiProcess = Start-Process -FilePath $venvPython -ArgumentList $apiArgs -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $apiStdout -RedirectStandardError $apiStderr -PassThru
    Set-Content -Path $apiPidFile -Value $apiProcess.Id

    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$apiPort/api/health" -TimeoutSec 5 | Out-Null
            $apiOk = $true
            break
        } catch {
        }
    }
}

if (-not $apiOk) {
    throw "FastAPI did not become ready. Check $apiStderr and $apiStdout"
}

$frontendOk = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$frontendPort" -TimeoutSec 5 | Out-Null
    $frontendOk = $true
} catch {
    $frontendOk = $false
}

if (-not $frontendOk) {
    if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
        Push-Location $frontendDir
        try {
            npm install
        } finally {
            Pop-Location
        }
    }

    $frontendArgs = "/c npm run dev -- --host 127.0.0.1 --port $frontendPort"
    $frontendProcess = Start-Process -FilePath "cmd.exe" -ArgumentList $frontendArgs -WorkingDirectory $frontendDir -WindowStyle Hidden -RedirectStandardOutput $frontendStdout -RedirectStandardError $frontendStderr -PassThru
    Set-Content -Path $frontendPidFile -Value $frontendProcess.Id

    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$frontendPort" -TimeoutSec 5 | Out-Null
            $frontendOk = $true
            break
        } catch {
        }
    }
}

if (-not $frontendOk) {
    throw "React frontend did not become ready. Check $frontendStderr and $frontendStdout"
}

Start-Process "http://127.0.0.1:$frontendPort"
Write-Host "SpecForge frontend: http://127.0.0.1:$frontendPort"
Write-Host "SpecForge API: http://127.0.0.1:$apiPort/api/health"
Write-Host "llama.cpp model: $modelPath"
Write-Host "reasoning mode: $reasoningMode"
