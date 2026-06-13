$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvStreamlit = Join-Path $root ".venv\Scripts\streamlit.exe"
$runtimeDir = Join-Path $root ".runtime"
$logsDir = Join-Path $runtimeDir "logs"
$serverPidFile = Join-Path $runtimeDir "llama-server.pid"
$streamlitPidFile = Join-Path $runtimeDir "streamlit.pid"
$serverStdout = Join-Path $logsDir "llama-server.stdout.log"
$serverStderr = Join-Path $logsDir "llama-server.stderr.log"
$streamlitStdout = Join-Path $logsDir "streamlit.stdout.log"
$streamlitStderr = Join-Path $logsDir "streamlit.stderr.log"

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment missing at $venvPython. Install dependencies first."
}

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
$streamlitPort = if ($env:SPECFORGE_STREAMLIT_PORT) { $env:SPECFORGE_STREAMLIT_PORT } else { "8501" }

if (-not (Test-Path $serverExe)) {
    throw "llama-server executable not found at $serverExe"
}
if (-not (Test-Path $modelPath)) {
    throw "GGUF model not found at $modelPath"
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

$streamlitOk = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$streamlitPort" -TimeoutSec 5 | Out-Null
    $streamlitOk = $true
} catch {
    $streamlitOk = $false
}

if (-not $streamlitOk) {
    $streamlitArgs = "run app.py --server.port $streamlitPort --server.headless true"
    $streamlitProcess = Start-Process -FilePath $venvStreamlit -ArgumentList $streamlitArgs -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $streamlitStdout -RedirectStandardError $streamlitStderr -PassThru
    Set-Content -Path $streamlitPidFile -Value $streamlitProcess.Id

    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$streamlitPort" -TimeoutSec 5 | Out-Null
            $streamlitOk = $true
            break
        } catch {
        }
    }
}

if (-not $streamlitOk) {
    throw "Streamlit did not become ready. Check $streamlitStderr and $streamlitStdout"
}

Start-Process "http://127.0.0.1:$streamlitPort"
Write-Host "SpecForge is running at http://127.0.0.1:$streamlitPort"
Write-Host "llama.cpp model: $modelPath"
Write-Host "reasoning mode: $reasoningMode"
