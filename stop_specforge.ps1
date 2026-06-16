$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $root ".runtime"
$serverPidFile = Join-Path $runtimeDir "llama-server.pid"
$apiPidFile = Join-Path $runtimeDir "api.pid"
$frontendPidFile = Join-Path $runtimeDir "frontend.pid"
$streamlitPidFile = Join-Path $runtimeDir "streamlit.pid"

foreach ($pidFile in @($frontendPidFile, $apiPidFile, $streamlitPidFile, $serverPidFile)) {
    if (Test-Path $pidFile) {
        $pidValue = Get-Content $pidFile | Select-Object -First 1
        if ($pidValue) {
            Stop-Process -Id ([int]$pidValue) -Force
        }
        Remove-Item $pidFile -Force
    }
}

powershell -ExecutionPolicy Bypass -File (Join-Path $root "stop_local_postgres.ps1")

Write-Host "SpecForge background processes stopped."
