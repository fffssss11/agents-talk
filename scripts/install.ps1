param(
    [string[]]$Clients = @('codex', 'claude', 'zcode'),
    [switch]$NoShortcut,
    [switch]$Preview
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'python.ps1')
$pythonExe = Find-AgentsTalkPython
$arguments = @((Join-Path $PSScriptRoot 'install_skills.py'), '--clients') + $Clients
if (-not $Preview) { $arguments += '--apply' }
& $pythonExe @arguments
if ($LASTEXITCODE -ne 0) { throw 'Skill installation failed; inspect the message above.' }
if ($Preview) { return }
$pythonExe | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'python-path.txt') -Encoding UTF8
if (-not $NoShortcut) {
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Agents Talk.lnk'
    if (Test-Path -LiteralPath $shortcutPath) {
        $backup = Join-Path $projectRoot ('.backups\shortcuts\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
        New-Item -ItemType Directory -Path $backup -Force | Out-Null
        Copy-Item -LiteralPath $shortcutPath -Destination $backup
    }
    $wsh = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'launch.vbs') + '"'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = 'Open the local Agents Talk dashboard'
    $shortcut.IconLocation = (Join-Path $env:WINDIR 'System32\shell32.dll') + ',14'
    $shortcut.Save()
    Write-Output "Desktop shortcut: $shortcutPath"
}
