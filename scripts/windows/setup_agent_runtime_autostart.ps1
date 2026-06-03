# Setup Agent Runtime Auto-Start via Task Scheduler
# Скрипт создает единственную запланированную задачу для Agent Runtime.

param(
    [string]$ProjectRoot = "",
    [string]$TaskName = "Portal Agent Runtime",
    [string]$TaskPath = "\Portal\",
    [string]$BindHost = "127.0.0.1",
    [int]$RuntimePort = 8090,
    [switch]$Force,
    [switch]$CleanupOnly
)

$ErrorActionPreference = "Stop"

Write-Host "=== Setup Agent Runtime Auto-Start ===" -ForegroundColor Cyan

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

# Настройки задачи
$pythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$workingDir = $ProjectRoot
$arguments = "-m uvicorn services.agent_runtime.app:app --host $BindHost --port $RuntimePort --timeout-keep-alive 300 --log-level info"

function Get-TaskActionText($Task) {
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($action in @($Task.Actions)) {
        $parts.Add("$($action.Execute) $($action.Arguments)")
    }
    return ($parts -join " ")
}

function Test-AgentRuntimeTask($Task) {
    $actionText = Get-TaskActionText $Task
    if ($Task.TaskName -eq $TaskName) {
        return $true
    }

    $looksLikeRuntime = (
        $actionText -like "*services.agent_runtime.app*" -or
        $actionText -like "*agent_runtime*" -or
        $actionText -like "*start_agent_runtime*"
    )
    $looksLikeSamePort = (
        $actionText -like "*$RuntimePort*" -or
        $actionText -like "*services.agent_runtime.app*" -or
        $actionText -like "*start_agent_runtime*"
    )
    return ($looksLikeRuntime -and $looksLikeSamePort)
}

function Remove-TaskIfAllowed($Task, [string]$Reason) {
    Write-Host "Найдена задача для удаления: $($Task.TaskPath)$($Task.TaskName)" -ForegroundColor Yellow
    Write-Host "  Причина: $Reason" -ForegroundColor Gray
    Write-Host "  Action: $(Get-TaskActionText $Task)" -ForegroundColor Gray

    if (-not $Force) {
        $response = Read-Host "Удалить эту задачу? (y/N)"
        if ($response -ne "y" -and $response -ne "Y") {
            Write-Host "  Пропущено" -ForegroundColor Yellow
            return
        }
    }

    Unregister-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath -Confirm:$false
    Write-Host "  Удалена" -ForegroundColor Green
}

# Проверка прав администратора
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ОШИБКА: Требуются права администратора" -ForegroundColor Red
    Write-Host "Запустите PowerShell от имени администратора" -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ Права администратора подтверждены" -ForegroundColor Green

# Проверка Python
if (-not (Test-Path $pythonPath)) {
    Write-Host "ОШИБКА: Python не найден по пути: $pythonPath" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Python найден: $pythonPath" -ForegroundColor Green

# Проверка рабочей директории
if (-not (Test-Path $workingDir)) {
    Write-Host "ОШИБКА: Рабочая директория не найдена: $workingDir" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Рабочая директория найдена: $workingDir" -ForegroundColor Green

# Удаление старых задач, которые могли запускать тот же runtime через системный Python.
$runtimeTasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { Test-AgentRuntimeTask $_ })
$staleTasks = @(
    $runtimeTasks | Where-Object {
        $_.TaskName -ne $TaskName -or $_.TaskPath -ne $TaskPath
    }
)

foreach ($task in $staleTasks) {
    Remove-TaskIfAllowed $task "устаревший или дублирующий автозапуск Agent Runtime"
}

if ($CleanupOnly) {
    Write-Host "CleanupOnly: регистрация новой задачи пропущена" -ForegroundColor Yellow
    exit 0
}

# Проверка, существует ли целевая задача
$existingTask = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "ВНИМАНИЕ: Задача '$TaskName' уже существует в $TaskPath" -ForegroundColor Yellow
    if (-not $Force) {
        $response = Read-Host "Перезаписать? (y/N)"
        if ($response -ne "y" -and $response -ne "Y") {
            Write-Host "Отмена" -ForegroundColor Yellow
            exit 0
        }
    }
    Write-Host "Удаление существующей задачи..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
    Write-Host "✓ Существующая задача удалена" -ForegroundColor Green
}

# Создание action с прямым запуском Python из .venv.
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $workingDir

Write-Host "✓ Action создан: $pythonPath $arguments" -ForegroundColor Green

# Создание триггера при старте системы
$trigger = New-ScheduledTaskTrigger -AtStartup

Write-Host "✓ Триггер создан (старт системы)" -ForegroundColor Green

# Настройки principal (запуск от имени SYSTEM)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Write-Host "✓ Principal создан (SYSTEM, Highest level)" -ForegroundColor Green

# Настройки
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 3) -MultipleInstances IgnoreNew

Write-Host "✓ Настройки созданы" -ForegroundColor Green

# Регистрация задачи
try {
    Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "AI Agent Runtime for Corporate Portal VOBB3 - auto-start at system boot" -ErrorAction Stop
    Write-Host "✓ Задача успешно зарегистрирована" -ForegroundColor Green
} catch {
    Write-Host "ОШИБКА при регистрации задачи:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# Проверка регистрации
$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "✓ Задача создана: ($task.TaskPath + $task.TaskName)" -ForegroundColor Green
    Write-Host "  Статус: $($task.State)" -ForegroundColor Cyan
} else {
    Write-Host "ОШИБКА: Задача не найдена после регистрации" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Настройка завершена ===" -ForegroundColor Green
Write-Host ""
Write-Host "Информация о задаче:" -ForegroundColor Cyan
Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath | Select-Object TaskName, State, Description | Format-List

Write-Host ""
Write-Host "Полезные команды:" -ForegroundColor Yellow
Write-Host "  Проверить задачу:" -ForegroundColor Gray
Write-Host "    Get-ScheduledTask -TaskName '$TaskName' -TaskPath '$TaskPath'" -ForegroundColor White
Write-Host ""
Write-Host "  Посмотреть детали:" -ForegroundColor Gray
Write-Host "    Get-ScheduledTaskInfo -TaskName '$TaskName' -TaskPath '$TaskPath'" -ForegroundColor White
Write-Host ""
Write-Host "  Запустить вручную:" -ForegroundColor Gray
Write-Host "    Start-ScheduledTask -TaskName '$TaskName' -TaskPath '$TaskPath'" -ForegroundColor White
Write-Host ""
Write-Host "  Остановить:" -ForegroundColor Gray
Write-Host "    Stop-ScheduledTask -TaskName '$TaskName' -TaskPath '$TaskPath'" -ForegroundColor White
Write-Host ""
Write-Host "  Удалить:" -ForegroundColor Gray
Write-Host "    Unregister-ScheduledTask -TaskName '$TaskName' -TaskPath '$TaskPath' -Confirm:`$false" -ForegroundColor White
Write-Host ""
Write-Host "  Найти все задачи Agent Runtime:" -ForegroundColor Gray
Write-Host "    Get-ScheduledTask | Where-Object { (`$_.TaskName -eq '$TaskName') -or ((`$_.Actions | Out-String) -like '*agent_runtime*') }" -ForegroundColor White
Write-Host ""
Write-Host "Проверка работы:" -ForegroundColor Yellow
Write-Host "  1. Перезагрузите сервер или запустите задачу вручную" -ForegroundColor Cyan
Write-Host "  2. Проверьте health endpoint:" -ForegroundColor Cyan
Write-Host "     Invoke-RestMethod -Uri 'http://$BindHost`:$RuntimePort/health'" -ForegroundColor White
Write-Host "  3. Проверьте логи в Event Viewer -> Task Scheduler" -ForegroundColor Cyan

Write-Host ""
Write-Host "✓ Скрипт завершен успешно" -ForegroundColor Green
