# DiscordWow - installs (or removes) the companion's auto-start at Windows logon.
#
# The companion costs almost nothing while idle: it just waits for the WoW
# window to appear, so the simplest way to "run whenever I open the game" is
# to keep it always up, invisible, via a Scheduled Task with pythonw.exe.
#
# Usage (PowerShell, in the companion folder):
#   .\install_autostart.ps1            # installs and starts right away
#   .\install_autostart.ps1 -Remove    # uninstalls
#
# Logs: no console; everything goes to companion.log next to main.py.

param(
    [switch]$Remove,
    [string]$TaskName = "DiscordWow Companion"
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Tarefa '$TaskName' removida."
    return
}

# pythonw = python without a console window
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    # fallback: derive it from the regular python (same folder)
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if ($python) { $pythonw = Join-Path (Split-Path $python) "pythonw.exe" }
}
if (-not $pythonw -or -not (Test-Path $pythonw)) {
    throw "pythonw.exe nao encontrado - instale o Python 3.10+ (python.org) com a opcao 'Add to PATH'."
}

$companionDir = $PSScriptRoot
$mainPy = Join-Path $companionDir "main.py"
if (-not (Test-Path $mainPy)) { throw "main.py nao encontrado em $companionDir" }
if (-not (Test-Path (Join-Path $companionDir "config.json"))) {
    throw "config.json nao encontrado - copie config.example.json e preencha antes de instalar."
}

$action = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "`"$mainPy`"" -WorkingDirectory $companionDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# no time limit (the task lives as long as the session does) and no fussing
# over laptop battery
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Tarefa '$TaskName' instalada e iniciada."
Write-Host "O companion agora sobe sozinho em todo logon do Windows (invisivel)."
Write-Host "Log: $companionDir\companion.log"
Write-Host "Parar agora:  Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Desinstalar:  .\install_autostart.ps1 -Remove"
