param([switch]$Once)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'python.ps1')
$pythonExe = Find-AgentsTalkPython
do {
    if (-not $Once) { Clear-Host }
    # Human-operated terminal view; never reports an agent read heartbeat.
    & $pythonExe (Join-Path $projectRoot 'hub.py') status
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $Once) { Start-Sleep -Seconds 3 }
} while (-not $Once)
