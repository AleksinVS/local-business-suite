# Диагностика автозапуска Agent Runtime без изменения системы.

param(
    [string]$TaskName = "Portal Agent Runtime",
    [int]$RuntimePort = 8090
)

$ErrorActionPreference = "Stop"

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

Write-Host "=== Agent Runtime autostart diagnostics ===" -ForegroundColor Cyan
Write-Host ""

$tasks = @(
    Get-ScheduledTask -ErrorAction SilentlyContinue |
        Where-Object {
            $_.TaskName -eq $TaskName -or (Test-AgentRuntimeAction (Get-TaskActionText $_))
        }
)

Write-Host "Scheduled tasks:" -ForegroundColor Yellow
if ($tasks.Count -eq 0) {
    Write-Host "  Задачи Agent Runtime не найдены" -ForegroundColor Gray
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
$processes = @(
    Get-CimInstance Win32_Process -Filter "name = 'python.exe' or name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -like "*services.agent_runtime.app*" -or
            (
                $_.CommandLine -like "*uvicorn*" -and
                $_.CommandLine -like "*$RuntimePort*"
            )
        }
)

if ($processes.Count -eq 0) {
    Write-Host "  Запущенные процессы Agent Runtime не найдены" -ForegroundColor Gray
} else {
    $processes |
        Select-Object ProcessId, ExecutablePath, CommandLine |
        Format-List
}

Write-Host ""
if ($tasks.Count -gt 1) {
    Write-Host "ВНИМАНИЕ: найдено несколько задач автозапуска Agent Runtime." -ForegroundColor Red
    Write-Host "Оставьте одну целевую задачу: $TaskName в \Portal\." -ForegroundColor Yellow
}
if ($processes.Count -gt 1) {
    Write-Host "ВНИМАНИЕ: найдено несколько процессов Agent Runtime." -ForegroundColor Red
    Write-Host "Проверьте задачи выше и остановите лишний процесс перед повторным автозапуском." -ForegroundColor Yellow
}
if ($tasks.Count -le 1 -and $processes.Count -le 1) {
    Write-Host "Дубли автозапуска по задачам и процессам не обнаружены." -ForegroundColor Green
}
