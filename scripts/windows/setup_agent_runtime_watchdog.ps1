<#
.SYNOPSIS
    Register the Agent Runtime health-check watchdog as a scheduled task.

.DESCRIPTION
    Creates a scheduled task \Portal\Portal Agent Runtime Watchdog that
    runs scripts\windows\watchdog_agent_runtime.ps1 every 2 minutes
    starting at system boot. The watchdog pings the runtime's /health
    endpoint and, after 3 consecutive failures, kills any stuck
    uvicorn process and asks Task Scheduler to re-run the main
    runtime task. The watchdog itself is supervised by Task Scheduler
    triggers — if it ever fails to fire, the next trigger fires it
    again. No external service supervisor required.

    Requires administrator privileges (same as the main runtime
    setup_agent_runtime_autostart.ps1).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\windows\setup_agent_runtime_watchdog.ps1 -Force
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$TaskName = "Portal Agent Runtime Watchdog",
    [string]$TaskPath = "\Portal\",
    [int]$RepetitionMinutes = 2,
    [string]$HealthUrl = "http://127.0.0.1:8090/health",
    [switch]$Force,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

if (-not $TaskPath.StartsWith("\")) { $TaskPath = "\$TaskPath" }
if (-not $TaskPath.EndsWith("\")) { $TaskPath = "$TaskPath\" }

# --- admin check ---
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Administrator privileges required. Re-run from an elevated PowerShell." -ForegroundColor Red
    exit 1
}

# --- unregister (if Remove or Force with existing task) ---
$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($existing -and $Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
    Write-Host "Watchdog task removed" -ForegroundColor Green
    exit 0
}
if ($existing) {
    if (-not $Force) {
        Write-Host "Watchdog task '$TaskName' already exists in $TaskPath. Re-run with -Force to overwrite." -ForegroundColor Yellow
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
}

# --- build action, trigger, principal, settings ---
$scriptPath = Join-Path $ProjectRoot "scripts\windows\watchdog_agent_runtime.ps1"
if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: watchdog script not found at $scriptPath" -ForegroundColor Red
    exit 1
}

$arguments = @"
-NoProfile -ExecutionPolicy Bypass -File "$scriptPath" -HealthUrl "$HealthUrl"
"@.Trim()
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments

# Repeating trigger. We use -Once -At (now) with -RepetitionInterval
# and -RepetitionDuration because that combination reliably creates a
# trigger that fires, then repeats every N minutes for N days. The
# pattern that was here before — -AtStartup followed by an after-the-fact
# assignment of the Repetition property — registered the task but left
# the trigger with an empty Repetition.Interval, so the trigger fired
# exactly twice (at boot) and then silently stopped. StartWhenAvailable
# in $settings below makes the task fire after a missed trigger (e.g.
# the machine was off when the next repetition was due).
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $RepetitionMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# StartWhenAvailable lets the watchdog fire after a missed trigger
# (e.g. machine was off). MultipleInstancesIgnoreNew means: if a
# previous cycle is somehow still running, do not start a new one.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 1)

# --- register ---
try {
    Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath `
        -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings `
        -Description "Pings Agent Runtime /health every $RepetitionMinutes min and restarts it after 3 consecutive failures." `
        -ErrorAction Stop
    Write-Host "Watchdog task registered:" -ForegroundColor Green
    Write-Host "  $TaskPath$TaskName" -ForegroundColor Cyan
    Write-Host "  repeats every $RepetitionMinutes minutes after system boot" -ForegroundColor Cyan
    Write-Host "  monitor: $HealthUrl" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Useful commands:" -ForegroundColor Yellow
    Write-Host "  Inspect task:" -ForegroundColor Gray
    Write-Host "    Get-ScheduledTask -TaskName '$TaskName' -TaskPath '$TaskPath' | Format-List" -ForegroundColor White
    Write-Host "  Inspect last run:" -ForegroundColor Gray
    Write-Host "    Get-ScheduledTaskInfo -TaskName '$TaskName' -TaskPath '$TaskPath'" -ForegroundColor White
    Write-Host "  Tail watchdog log:" -ForegroundColor Gray
    Write-Host "    Get-Content (Join-Path '$ProjectRoot' '.local\watchdog.log') -Tail 50" -ForegroundColor White
    Write-Host "  Remove watchdog task:" -ForegroundColor Gray
    Write-Host "    powershell -ExecutionPolicy Bypass -File $PSCommandPath -Remove" -ForegroundColor White
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
