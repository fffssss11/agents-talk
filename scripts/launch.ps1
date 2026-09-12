param([switch]$NoOpen, [ValidateRange(1,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
$serverStem = if ($Port -eq 8765) { 'server' } else { 'server-' + $Port }
$expectedVersion = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
$launchMutex = New-Object System.Threading.Mutex($false, ('Local\AgentsTalkDashboard' + $Port))
$acquired = $false
$serverProcess = $null
$isReady = $false
try {
    try { $acquired = $launchMutex.WaitOne(20000) } catch [System.Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { throw 'Another dashboard launch is still running.' }
    $panelUrl = 'http://127.0.0.1:' + $Port + '/'
    $dataPath = if ($env:AGENTS_TALK_DATA) { [IO.Path]::GetFullPath($env:AGENTS_TALK_DATA) } else { $projectRoot }
    $configPath = if ($env:AGENTS_TALK_CONFIG) { [IO.Path]::GetFullPath($env:AGENTS_TALK_CONFIG) } else { Join-Path $projectRoot 'config.json' }
    $isReady = $false
    try {
        $probe = Invoke-RestMethod -Uri ($panelUrl + 'api/health') -TimeoutSec 2
        if ($probe.app -ne 'agents-talk' -or $probe.version -ne 2 -or ($probe.root -ne $projectRoot -or $probe.data -ne $dataPath -or $probe.config -ne $configPath -or $probe.app_version -ne $expectedVersion)) {
            throw 'PORT_IN_USE'
        }
        $isReady = $true
    } catch {
        if ($_.Exception.Message -eq 'PORT_IN_USE') { throw "Port $Port is occupied by another project/data/config or an older running version. Stop it explicitly or choose another port." }
    }
    if (-not $isReady) {
        $socket = New-Object System.Net.Sockets.TcpClient
        try {
            $connected = $socket.ConnectAsync('127.0.0.1', $Port).Wait(1000)
            if ($connected -and $socket.Connected) { throw 'PORT_OCCUPIED' }
        } catch {
            if ($_.Exception.Message -eq 'PORT_OCCUPIED') { throw "Port $Port is occupied by an unrecognized or older service. No process was stopped." }
        } finally { $socket.Dispose() }
        . (Join-Path $PSScriptRoot 'python.ps1')
        $pythonPath = Find-AgentsTalkPython
        $hubPath = Join-Path $projectRoot 'hub.py'
        $serverArguments = '"' + $hubPath + '" serve --no-open --port ' + $Port
        $serverProcess = Start-Process -FilePath $pythonPath -ArgumentList $serverArguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimePath ($serverStem + '.log')) -RedirectStandardError (Join-Path $runtimePath ($serverStem + '-error.log')) -PassThru
        $serverProcess.Id | Set-Content -LiteralPath (Join-Path $runtimePath ($serverStem + '.pid'))
        $startupClock = [System.Diagnostics.Stopwatch]::StartNew()
        while ($startupClock.Elapsed.TotalSeconds -lt 30) {
            Start-Sleep -Milliseconds 250
            try {
                $probe = Invoke-RestMethod -Uri ($panelUrl + 'api/health') -TimeoutSec 1
                if ($probe.app -eq 'agents-talk' -and $probe.version -eq 2 -and $probe.pid -eq $serverProcess.Id -and $probe.root -eq $projectRoot -and $probe.data -eq $dataPath -and $probe.config -eq $configPath -and $probe.app_version -eq $expectedVersion) { $isReady = $true; break }
            } catch { }
            if ($serverProcess.HasExited) { break }
        }
        if (-not $isReady) { throw ('Dashboard failed to start. Open .runtime/' + $serverStem + '-error.log in the project folder.') }
    }
    if (-not $NoOpen) { Start-Process $panelUrl }
} catch {
    # Only clean up the child launched by this invocation, never an existing service.
    if ($serverProcess -and -not $isReady -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -ErrorAction SilentlyContinue
    }
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $runtimePath 'launch-error.log') -Encoding UTF8
    if ($NoOpen) { throw }
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message, 'Agents Talk') | Out-Null
    exit 1
} finally {
    if ($acquired) { $launchMutex.ReleaseMutex() }
    $launchMutex.Dispose()
}
