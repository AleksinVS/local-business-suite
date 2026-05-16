# Setup Agent Runtime Auto-Start via Task Scheduler
# Скрипт создает запланированную задачу для автоматического запуска Agent Runtime

param(
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"

Write-Host "=== Setup Agent Runtime Auto-Start ===" -ForegroundColor Cyan

# Настройки задачи
$taskName = "Portal Agent Runtime"
$taskPath = "\Portal\"
$pythonPath = "C:\inetpub\portal\.venv\Scripts\python.exe"
$workingDir = "C:\inetpub\portal"
$arguments = "-m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300 --log-level info"

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

# Проверка, существует ли задача
$existingTask = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "ВНИМАНИЕ: Задача '$taskName' уже существует" -ForegroundColor Yellow
    if (-not $Force) {
        $response = Read-Host "Перезаписать? (y/N)"
        if ($response -ne "y" -and $response -ne "Y") {
            Write-Host "Отмена" -ForegroundColor Yellow
            exit 0
        }
    }
    Write-Host "Удаление существующей задачи..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Confirm:$false
    Write-Host "✓ Существующая задача удалена" -ForegroundColor Green
}

# Создание bat-файла для запуска
Write-Host "Создание bat-файла для запуска..." -ForegroundColor Cyan

$batContent = "@echo off
cd /d C:\inetpub\portal
C:\inetpub\portal\.venv\Scripts\python.exe -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300 --log-level info"

$batFilePath = "C:\inetpub\portal\start_agent_runtime.bat"
$batContent | Set-Content -Path $batFilePath -Encoding ASCII

Write-Host "✓ Bat-файл создан: $batFilePath" -ForegroundColor Green

# Создание action с использованием bat-файла
$action = New-ScheduledTaskAction -Execute $batFilePath -WorkingDirectory $workingDir

Write-Host "✓ Action создан (через bat-файл)" -ForegroundColor Green

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
    Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "AI Agent Runtime for Corporate Portal VOBB3 - auto-start at system boot" -ErrorAction Stop
    Write-Host "✓ Задача успешно зарегистрирована" -ForegroundColor Green
} catch {
    Write-Host "ОШИБКА при регистрации задачи:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# Проверка регистрации
$task = Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath -ErrorAction SilentlyContinue
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
Get-ScheduledTask -TaskName $taskName -TaskPath $taskPath | Select-Object TaskName, State, Description | Format-List

Write-Host ""
Write-Host "Полезные команды:" -ForegroundColor Yellow
Write-Host "  Проверить задачу:" -ForegroundColor Gray
Write-Host "    Get-ScheduledTask -TaskName '' -TaskPath ''" -ForegroundColor White
Write-Host ""
Write-Host "  Посмотреть детали:" -ForegroundColor Gray
Write-Host "    Get-ScheduledTaskInfo -TaskName '' -TaskPath ''" -ForegroundColor White
Write-Host ""
Write-Host "  Запустить вручную:" -ForegroundColor Gray
Write-Host "    Start-ScheduledTask -TaskName '' -TaskPath ''" -ForegroundColor White
Write-Host ""
Write-Host "  Остановить:" -ForegroundColor Gray
Write-Host "    Stop-ScheduledTask -TaskName '' -TaskPath ''" -ForegroundColor White
Write-Host ""
Write-Host "  Удалить:" -ForegroundColor Gray
Write-Host "    Unregister-ScheduledTask -TaskName '' -TaskPath '' -Confirm:$false" -ForegroundColor White
Write-Host ""
Write-Host "  Запустить вручную через bat-файл:" -ForegroundColor Gray
Write-Host "    C:\inetpub\portal\start_agent_runtime.bat" -ForegroundColor White
Write-Host ""
Write-Host "Проверка работы:" -ForegroundColor Yellow
Write-Host "  1. Перезагрузите сервер или запустите задачу вручную" -ForegroundColor Cyan
Write-Host "  2. Проверьте health endpoint:" -ForegroundColor Cyan
Write-Host "     Invoke-RestMethod -Uri 'http://127.0.0.1:8090/health'" -ForegroundColor White
Write-Host "  3. Проверьте логи в Event Viewer -> Task Scheduler" -ForegroundColor Cyan

Write-Host ""
Write-Host "✓ Скрипт завершен успешно" -ForegroundColor Green
