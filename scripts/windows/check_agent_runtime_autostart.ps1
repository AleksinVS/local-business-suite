# Diagnostics of Agent Runtime autostart without modifying the system.
#
# Distinguishes:
#   * normal uvicorn multiprocessing (1 scheduled task + 1 root master
#     + 0..N worker subprocesses);
#   * real duplicate (multiple scheduled tasks, or multiple root
#     processes not related by parent-child).
#
# Why wmic may show two different ExecutablePath values
# (`.venv\Scripts\python.exe` and `C:\Program Files\Python311\python.exe`)
# for a single logical run: this venv was built on top of the system
# Python 3.11 (see `.venv\pyvenv.cfg: executable = ...`), and
# `multiprocessing.spawn` launches the worker subprocess with
# `sys.executable` of the parent - which after venv re-exec points to
# the system interpreter.

param(
    [string]$TaskName = "Portal Agent Runtime",
    [string]$TaskPath = "\Portal\",
    [int]$RuntimePort = 8090,
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

if (-not $TaskPath.StartsWith("\")) {
    $TaskPath = "\$TaskPath"
}
if (-not $TaskPath.EndsWith("\")) {
    $TaskPath = "$TaskPath\"
}

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$expectedPythons = New-Object System.Collections.Generic.List[string]
$expectedPythons.Add($venvPython)

$pyvenvCfg = Join-Path $ProjectRoot ".venv\pyvenv.cfg"
if (Test-Path $pyvenvCfg) {
    foreach ($line in (Get-Content $pyvenvCfg -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*executable\s*=\s*(.+?)\s*$') {
            $real = $Matches[1].Trim()
            if ($real -and -not $expectedPythons.Contains($real)) {
                $expectedPythons.Add($real)
            }
        }
    }
}

function Get-TaskActionText($Task) {
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($action in @($Task.Actions)) {
        $parts.Add("$($action.Execute) $($action.Arguments)")
    }
    return ($parts -join " ")
}

function Test-AgentRuntimeAction([string]$ActionText) {
    return (
        $ActionText -like "*services.agent_runtime.app*" -or
        $ActionText -like "*agent_runtime*" -or
        $ActionText -like "*start_agent_runtime*" -or
        (
            $ActionText -like "*uvicorn*" -and
            $ActionText -like "*$RuntimePort*"
        )
    )
}

function Get-RuntimeProcesses {
    return @(
        Get-CimInstance Win32_Process -Filter "name = 'python.exe' or name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.CommandLine -like "*services.agent_runtime.app*" -or
                (
                    $_.CommandLine -like "*uvicorn*" -and
                    $_.CommandLine -like "*$RuntimePort*"
                )
            }
    )
}

function Split-RuntimeProcessesByParent($processes) {
    $byPid = @{}
    foreach ($p in $processes) {
        $byPid[[int]$p.ProcessId] = $p
    }
    $roots = New-Object System.Collections.Generic.List[object]
    $workers = New-Object System.Collections.Generic.List[object]
    foreach ($p in $processes) {
        $ppid = [int]$p.ParentProcessId
        if ($byPid.ContainsKey($ppid)) {
            $workers.Add($p)
        } else {
            $roots.Add($p)
        }
    }
    return @{ Roots = $roots; Workers = $workers; All = $processes }
}

function Test-ExpectedPython([string]$exe) {
    if ([string]::IsNullOrWhiteSpace($exe)) { return $false }
    foreach ($expected in $expectedPythons) {
        if ([string]::Equals($exe, $expected, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

Write-Host "=== Agent Runtime autostart diagnostics ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Expected Python paths:"
foreach ($p in $expectedPythons) {
    Write-Host "  - $p"
}
Write-Host ""

# --- Scheduled tasks ---
$tasks = @(
    Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object {
            $_.TaskName -eq $TaskName -or (Test-AgentRuntimeAction (Get-TaskActionText $_))
        }
)

Write-Host "Scheduled tasks:" -ForegroundColor Yellow
if ($tasks.Count -eq 0) {
    Write-Host "  No Agent Runtime scheduled tasks found" -ForegroundColor Gray
} else {
    foreach ($task in $tasks) {
        $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction SilentlyContinue
        [pscustomobject]@{
            TaskPath = $task.TaskPath
            TaskName = $task.TaskName
            State = $task.State
            LastRunTime = $info.LastRunTime
            LastTaskResult = $info.LastTaskResult
            Action = Get-TaskActionText $task
        } | Format-List
    }
}

Write-Host ""
Write-Host "Python processes:" -ForegroundColor Yellow
$processes = Get-RuntimeProcesses
if ($processes.Count -eq 0) {
    Write-Host "  No Agent Runtime python processes running" -ForegroundColor Gray
} else {
    $processes |
        Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine |
        Format-List
}

# --- Analysis ---
Write-Host ""
Write-Host "Analysis:" -ForegroundColor Yellow
$staleTasks = @($tasks | Where-Object { $_.TaskName -ne $TaskName -or $_.TaskPath -ne $TaskPath })
$expectedTask = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue

$realProblems = New-Object System.Collections.Generic.List[string]

if ($staleTasks.Count -gt 0) {
    $realProblems.Add("Found $($staleTasks.Count) foreign/stale scheduled task(s). Target is '$TaskName' in '$TaskPath'.")
}

if ($expectedTask) {
    $actionExe = (Get-TaskActionText $expectedTask) -split '\s+', 2 | Select-Object -First 1
    if (-not (Test-ExpectedPython $actionExe)) {
        $realProblems.Add("Target task uses unexpected Python: $actionExe.")
    }
} else {
    $realProblems.Add("Target task '$TaskName' in '$TaskPath' is not registered. Run setup_agent_runtime_autostart.ps1 -Force.")
}

$tree = Split-RuntimeProcessesByParent $processes
$rootCount = $tree.Roots.Count
$workerCount = $tree.Workers.Count

if ($processes.Count -gt 0 -and $rootCount -eq 0) {
    $realProblems.Add("Agent Runtime processes are running but none is a root. Possible cycle.")
} elseif ($rootCount -gt 1) {
    $realProblems.Add("Found $rootCount independent (root) Agent Runtime processes. This is a real duplicate. Compare EXE and run sources.")
} elseif ($rootCount -eq 1) {
    $rootExe = $tree.Roots[0].ExecutablePath
    if (Test-ExpectedPython $rootExe) {
        if ($workerCount -eq 0) {
            Write-Host "  OK: 1 root process (uvicorn master), worker subprocess not yet started" -ForegroundColor Green
        } else {
            Write-Host "  OK: 1 root process (uvicorn master) + $workerCount worker subprocess(es) (uvicorn multiprocessing). This is normal." -ForegroundColor Green
        }
    } else {
        $realProblems.Add("Root process uses $rootExe, expected one of: $($expectedPythons -join ', ').")
    }
}

if ($rootCount -eq 0 -and $workerCount -gt 0) {
    $realProblems.Add("Found $workerCount worker subprocess(es) but no root process. Master died, worker is hanging.")
}

Write-Host ""
if ($realProblems.Count -gt 0) {
    Write-Host "WARNING: real problems found:" -ForegroundColor Red
    foreach ($p in $realProblems) {
        Write-Host "  - $p" -ForegroundColor Red
    }
    if ($staleTasks.Count -gt 0) {
        Write-Host "  Remove foreign tasks: setup_agent_runtime_autostart.ps1 -Force" -ForegroundColor Yellow
    }
} else {
    Write-Host "OK: scheduled task and processes are in normal state." -ForegroundColor Green
    if ($rootCount -eq 1 -and $workerCount -ge 1) {
        Write-Host "  Two different ExecutablePath values (.venv\Scripts\python.exe and the system one) are master + worker of uvicorn multiprocessing, not a duplicate." -ForegroundColor Gray
    }
}
