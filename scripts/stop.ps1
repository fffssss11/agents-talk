param([ValidateRange(1,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$dataPath = if ($env:AGENTS_TALK_DATA) { [IO.Path]::GetFullPath($env:AGENTS_TALK_DATA) } else { $projectRoot }
$serverStem = if ($Port -eq 8765) { 'server' } else { 'server-' + $Port }
$pidPath = Join-Path $projectRoot ('.runtime\' + $serverStem + '.pid')
if (-not (Test-Path -LiteralPath $pidPath)) { throw 'No recorded background server. Stop a foreground server with Ctrl+C.' }
$serverId = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
$probe = Invoke-RestMethod -Uri ('http://127.0.0.1:' + $Port + '/api/health') -TimeoutSec 3
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverId"
$hub = Join-Path $projectRoot 'hub.py'
if ($probe.app -ne 'agents-talk' -or $probe.root -ne $projectRoot -or $probe.data -ne $dataPath -or $probe.pid -ne $serverId -or -not $process -or -not $process.CommandLine.Contains($hub) -or $process.CommandLine -notmatch '\bserve\b') {
    throw 'The PID, service, or directory does not match. No process was stopped.'
}
Stop-Process -Id $serverId -ErrorAction Stop
Write-Output 'Agents Talk background server stopped. Agent CLI processes and all data are unchanged.'
