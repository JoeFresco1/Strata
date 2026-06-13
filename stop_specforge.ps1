$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $root ".runtime"
$serverPidFile = Join-Path $runtimeDir "llama-server.pid"
$streamlitPidFile = Join-Path $runtimeDir "streamlit.pid"

foreach ($pidFile in @($streamlitPidFile, $serverPidFile)) {
    if (Test-Path $pidFile) {
        $pidValue = Get-Content $pidFile | Select-Object -First 1
        if ($pidValue) {
            Stop-Process -Id ([int]$pidValue) -Force
        }
        Remove-Item $pidFile -Force
    }
}

Write-Host "SpecForge background processes stopped."
