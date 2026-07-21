<#
.SYNOPSIS
    Health-check watchdog for the Agent Runtime process.

.DESCRIPTION
    Pings the runtime's /health endpoint a few times with a short timeout.
    If all pings fail, kills any stuck uvicorn process and asks Task
    Scheduler to re-run the main runtime task. Logs every check to
    .local/watchdog.log so failures are auditable in retrospect.

    Register as a scheduled task that repeats every 2 minutes. If the
    watchdog itself fails to run, the next scheduled trigger fires it
    again — no self-supervision needed.

.PARAMETER HealthUrl
    Full URL of the runtime's /health endpoint. Default
    http://127.0.0.1:8090/health.

.PARAMETER Attempts
    How many pings per cycle. Default 3.

.PARAMETER RetryDelaySeconds
    Seconds between retries within a single cycle. Default 10.

.PARAMETER LogPath
    Path to append-only log file. Default .local\watchdog.log relative
    to the script directory.

.EXAMPLE
    # Register as a 2-minute repeating scheduled task
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\inetpub\portal\scripts\windows\watchdog_agent_runtime.ps1"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Repetition = (New-CimInstance -ClassName MSFT_TaskRepetitionPattern `
        -Property @{ Interval = "PT2M" } -ClientOnly)
    Register-ScheduledTask -TaskName "Portal Agent Runtime Watchdog" `
        -TaskPath "\Portal\" -Action $action -Trigger $trigger `
        -Principal (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest) `
        -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable)
#>

[CmdletBinding()]
param(
    [string]$HealthUrl = "http://127.0.0.1:8090/health",
    [int]$Attempts = 3,
    [int]$RetryDelaySeconds = 10,
    [string]$LogPath
)

$ErrorActionPreference = "Continue"

if (-not $LogPath) {
    $LogPath = Join-Path (Split-Path -Parent $PSCommandPath) "..\..\.local\watchdog.log"
}
$logDir = Split-Path -Parent $LogPath
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$timestamp] [$Level] $Message"
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Test-HealthOnce {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Restart-AgentRuntime {
    Write-Log "All $Attempts health checks failed — restarting Agent Runtime"
    try {
        # Kill all uvicorn python processes (master + workers) so the
        # port is released and Task Scheduler can bind a fresh one.
        Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -like '*uvicorn*' } |
            ForEach-Object {
                Write-Log "killing uvicorn PID=$($_.ProcessId)"
                $_.Terminate() | Out-Null
            }
        Start-Sleep -Seconds 3
        # Ask Task Scheduler to fire the main runtime task immediately.
        Start-ScheduledTask -TaskName "Portal Agent Runtime" -TaskPath "\Portal\" -ErrorAction Stop
        Write-Log "Start-ScheduledTask issued; waiting for runtime to come up"
        Start-Sleep -Seconds 15
        $ok = Test-HealthOnce -Url $HealthUrl
        if ($ok) {
            Write-Log "Runtime is back online"
        } else {
            Write-Log "Runtime did not respond after restart; next watchdog cycle will retry" "WARN"
        }
    } catch {
        Write-Log "Restart failed: $($_.Exception.Message)" "ERROR"
    }
}

# --- main loop ---
$ok = $false
for ($i = 1; $i -le $Attempts; $i++) {
    $isHealthy = Test-HealthOnce -Url $HealthUrl
    if ($isHealthy) {
        $ok = $true
        break
    }
    Write-Log "Health check $i/$Attempts failed ($HealthUrl)"
    if ($i -lt $Attempts) {
        Start-Sleep -Seconds $RetryDelaySeconds
    }
}

if (-not $ok) {
    Restart-AgentRuntime
} else {
    Write-Log ('Runtime is healthy: ' + $Attempts + ' of ' + $Attempts + ' health checks passed')
}
