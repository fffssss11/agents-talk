function Find-AgentsTalkPython {
    $candidates = @()
    if ($env:AGENTS_TALK_PYTHON) { $candidates += $env:AGENTS_TALK_PYTHON }
    $saved = Join-Path $PSScriptRoot 'python-path.txt'
    if (Test-Path -LiteralPath $saved) { $candidates += (Get-Content -LiteralPath $saved -Raw).Trim() }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        # List installed interpreters without asking the launcher to install a runtime.
        $found = & $py.Source --list-paths 2>$null
        if ($LASTEXITCODE -eq 0) {
            foreach ($line in $found) {
                if ($line -match '(?i)([A-Z]:\\.*python(?:w)?\.exe)\s*$') { $candidates += $Matches[1] }
            }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate -or -not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            $found = & $candidate -c 'import sys; assert sys.version_info >= (3,10); print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { return ($found | Select-Object -Last 1).Trim() }
        } catch { }
    }
    throw 'Python 3.10+ was not found. Install Python, reopen the terminal, or set AGENTS_TALK_PYTHON to its executable.'
}
