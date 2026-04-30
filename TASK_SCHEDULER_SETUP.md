# 🚀 Настройка Agent Runtime через Task Scheduler

## Обзор

Этот документ содержит подробную инструкцию по настройке автоматического запуска Agent Runtime (AI-агента) через Task Scheduler в Windows.

## Содержание

1. [Вариант 1: Автоматическая настройка через PowerShell](#вариант-1-автоматическая-настройка-через-powershell)
2. [Вариант 2: Ручная настройка через GUI](#вариант-2-ручная-настройка-через-gui)
3. [Проверка работы](#проверка-работы)
4. [Управление задачей](#управление-задачей)
5. [Просмотр логов](#просмотр-логов)
6. [Частые проблемы](#частые-проблемы)
7. [Сравнение с Windows Service](#сравнение-с-windows-service)

---

## Вариант 1: Автоматическая настройка через PowerShell

### Инструкция:

Скопируйте и выполните этот код в PowerShell **от имени администратора**:

```powershell
# ========== НАСТРОЙКА TASK SCHEDULER ДЛЯ AGENT RUNTIME ==========

# 1. Создать действие (Action)
$action = New-ScheduledTaskAction `
    -Execute "C:\inetpub\portal\.venv\Scripts\python.exe" `
    -Argument "-m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300" `
    -WorkingDirectory "C:\inetpub\portal"

# 2. Создать триггер (Trigger) - запуск при старте системы
$trigger = New-ScheduledTaskTrigger -AtStartup

# 3. Создать настройки безопасности (Principal)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# 4. Создать настройки задачи (Settings)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StopIfGoingOnBatteries $false `
    -DisallowStartOnRemoteAppSession $false

# 5. Зарегистрировать задачу
Register-ScheduledTask `
    -TaskName "Portal Agent Runtime" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "AI Agent Runtime for Corporate Portal - runs on port 8090" `
    -Force

Write-Host "✅ Задача 'Portal Agent Runtime' успешно создана!" -ForegroundColor Green
Write-Host ""
Write-Host "Проверка задачи..." -ForegroundColor Yellow

# 6. Проверить созданную задачу
$task = Get-ScheduledTask -TaskName "Portal Agent Runtime"
Write-Host "Имя: $($task.TaskName)"
Write-Host "Статус: $($task.State)"
Write-Host "Последний запуск: $($task.LastRunTime)"
Write-Host "Следующий запуск: $($task.NextRunTime)"

# 7. Запустить задачу немедленно
Write-Host ""
Write-Host "Запуск задачи..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName "Portal Agent Runtime"

# 8. Подождать немного и проверить статус
Start-Sleep -Seconds 5
$task = Get-ScheduledTask -TaskName "Portal Agent Runtime"
Write-Host "Статус после запуска: $($task.State)"
Write-Host ""

# 9. Проверить, что порт 8090 доступен
Write-Host "Проверка порта 8090..." -ForegroundColor Yellow
$connection = Test-NetConnection -ComputerName 127.0.0.1 -Port 8090 -WarningAction SilentlyContinue
if ($connection.TcpTestSucceeded) {
    Write-Host "✅ Порт 8090 доступен!" -ForegroundColor Green

    # Проверить health endpoint
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" -TimeoutSec 10
        Write-Host "✅ Agent Runtime работает!" -ForegroundColor Green
        Write-Host "Статус: $($response.status)"
        Write-Host "Модель: $($response.model)"
    } catch {
        Write-Host "⚠️ Порт доступен, но health endpoint недоступен. Подождите еще немного." -ForegroundColor Yellow
    }
} else {
    Write-Host "❌ Порт 8090 недоступен. Проверьте логи задачи." -ForegroundColor Red
}

Write-Host ""
Write-Host "========== ИНСТРУКЦИЯ ПО УПРАВЛЕНИЮ ==========" -ForegroundColor Cyan
Write-Host "Открыть Task Scheduler: taskschd.msc"
Write-Host "Найти задачу: Portal Agent Runtime"
Write-Host ""
Write-Host "Команды управления:"
Write-Host "  Запустить:   Start-ScheduledTask -TaskName 'Portal Agent Runtime'"
Write-Host "  Остановить:   Stop-ScheduledTask -TaskName 'Portal Agent Runtime'"
Write-Host "  Удалить:     Unregister-ScheduledTask -TaskName 'Portal Agent Runtime' -Confirm:`$false"
Write-Host "  Проверить:    Get-ScheduledTask -TaskName 'Portal Agent Runtime'"
```

### Преимущества этого метода:
- ✅ Полная автоматизация
- ✅ Мгновенная настройка
- ✅ Автоматическая проверка работоспособности
- ✅ Все команды готовы к копированию

---

## Вариант 2: Ручная настройка через GUI

### Шаг 1: Открыть Task Scheduler
1. Нажмите `Win + R`
2. Введите `taskschd.msc`
3. Нажмите Enter

### Шаг 2: Создать задачу
1. В правой панели нажмите **"Create Task"** (или `Action` → `Create Task`)

### Шаг 3: Общие настройки (General tab)

**Name**: `Portal Agent Runtime`

**Description**: `AI Agent Runtime for Corporate Portal`

**Security options**:
- ☑️ **Run whether user is logged on or not**
- ☑️ **Run with highest privileges**
- ☑️ **Do not store password** (снимите, если не нужно)

**Configure for**: Выберите вашу версию Windows (например, `Windows Server 2016`)

### Шаг 4: Триггеры (Triggers tab)
1. Нажмите кнопку **"New..."**
2. **Begin the task**: `At startup`
3. **Settings**:
   - ☑️ **Enabled**
   - ☑️ **Delay task for**: `30 seconds`
   - ☑️ **Stop task if it runs longer than**: `3 days`
4. Нажмите **OK**

### Шаг 5: Действия (Actions tab)
1. Нажмите кнопку **"New..."**
2. **Action**: `Start a program`
3. **Program/script**: `C:\inetpub\portal\.venv\Scripts\python.exe`
4. **Add arguments**: `-m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300`
5. **Start in (optional)**: `C:\inetpub\portal`
6. Нажмите **OK**

### Шаг 6: Условия (Conditions tab)

**Power**:
- ☑️ **Start the task only if the computer is on AC power** (снимите, если сервер на UPS)

**Network**:
- ☑️ **Start only if the following network connection is available**
- Выберите: `Any connection`

**Idle**: (оставьте по умолчанию)

### Шаг 7: Настройки (Settings tab)
- ☑️ **Allow task to be run on demand**
- ☑️ **Run task as soon as possible after a scheduled start is missed**
- ☑️ **If the task fails, restart every**: `1 minute`
- ☑️ **Attempt to restart up to**: `3 times`
- ☑️ **Stop the task if it runs longer than**: `3 days`
- ☑️ **If the running task does not end when requested, force it to stop**
- ❌ **Do not start a new instance** (измените на "Stop the existing instance" если нужно)

### Шаг 8: Сохранить и запустить
1. Нажмите **OK**
2. В правой панели найдите задачу **"Portal Agent Runtime"**
3. Нажмите правой кнопкой мыши → **Run**

---

## Проверка работы

### После настройки выполните следующие команды:

```powershell
# 1. Проверить статус задачи
Get-ScheduledTask -TaskName "Portal Agent Runtime" | Select-Object TaskName, State, LastRunTime, NextRunTime

# 2. Проверить, что процесс работает
Get-Process python | Where-Object {$_.CommandLine -like "*uvicorn*agent_runtime*"}

# 3. Проверить порт
Test-NetConnection -ComputerName 127.0.0.1 -Port 8090

# 4. Проверить health endpoint
Invoke-RestMethod -Uri "http://127.0.0.1:8090/health"
```

### Ожидаемый результат:
- Статус задачи: `Ready` или `Running`
- Процесс python с uvicorn запущен
- Порт 8090 доступен
- Health endpoint возвращает `{"status": "ok", ...}`

---

## Управление задачей

### Через PowerShell:

```powershell
# Запустить задачу
Start-ScheduledTask -TaskName "Portal Agent Runtime"

# Остановить задачу
Stop-ScheduledTask -TaskName "Portal Agent Runtime"

# Проверить статус
Get-ScheduledTask -TaskName "Portal Agent Runtime"

# Удалить задачу
Unregister-ScheduledTask -TaskName "Portal Agent Runtime" -Confirm:$false

# Посмотреть подробную информацию
Get-ScheduledTaskInfo -TaskName "Portal Agent Runtime"
```

### Через графический интерфейс (Task Scheduler):

1. Откройте Task Scheduler (`taskschd.msc`)
2. Найдите задачу **"Portal Agent Runtime"**
3. Правой кнопкой мыши:

Доступные действия:
- **Run** - запустить задачу
- **End** - остановить задачу
- **Disable** - отключить задачу
- **Delete** - удалить задачу
- **Properties** - изменить настройки
- **History** - посмотреть историю запусков

---

## Просмотр логов

### Через Task Scheduler:

1. Откройте Task Scheduler
2. Найдите задачу **"Portal Agent Runtime"**
3. В правой панели нажмите **"History"**
4. Смотрите события:
   - ✅ **Task completed** - задача успешно запущена
   - ❌ **Task failed** - ошибка запуска
   - ⚠️ **Task stopped** - задача была остановлена

### Через PowerShell:

```powershell
# Посмотреть результат последнего запуска
Get-ScheduledTaskInfo -TaskName "Portal Agent Runtime" | Select-Object -ExpandProperty LastTaskResult

# Посмотреть последние 10 событий
Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" |
    Where-Object {$_.Message -like "*Portal Agent Runtime*"} |
    Select-Object TimeCreated, Id, Message |
    Sort-Object TimeCreated -Descending |
    Select-Object -First 10
```

### Через файловые логи (если настроены):

Если вы добавили логирование в Agent Runtime, проверьте:
```powershell
# Проверить директорию с логами
Get-ChildItem "C:\inetpub\portal\logs\" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 10
```

---

## Частые проблемы

### Проблема 1: Задача запускается, но порт недоступен

**Причина**: Возможно, нужно увеличить задержку запуска или возникают ошибки при старте.

**Решение**:

```powershell
# Получить текущую задачу
$task = Get-ScheduledTask -TaskName "Portal Agent Runtime"

# Изменить триггер - добавить задержку 60 секунд
$trigger = New-ScheduledTaskTrigger -AtStartup
# Задержка не может быть задана напрямую через AtStartup, поэтому используем другой подход

# Обновим настройки с увеличенным количеством перезапусков
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2)

Set-ScheduledTask -TaskName "Portal Agent Runtime" -Settings $settings

# Перезапустить задачу
Stop-ScheduledTask -TaskName "Portal Agent Runtime"
Start-ScheduledTask -TaskName "Portal Agent Runtime"
```

**Дополнительное решение**: Проверьте логи Task Scheduler для более детальной диагностики.

---

### Проблема 2: Задача падает и не перезапускается

**Причина**: Недостаточно настроек перезапуска или критическая ошибка в коде.

**Решение**:

```powershell
# Получить текущую задачу
$task = Get-ScheduledTask -TaskName "Portal Agent Runtime"

# Обновить настройки с более агрессивным перезапуском
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 10 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StopIfGoingOnBatteries $false `
    -AllowHardTerminate $true

Set-ScheduledTask -TaskName "Portal Agent Runtime" -Settings $settings

# Проверить историю запусков
Get-ScheduledTaskInfo -TaskName "Portal Agent Runtime"
```

**Важно**: Если задача постоянно падает, проверьте:
1. Есть ли все необходимые зависимости (Python, модули)
2. Правильный ли путь к Python
3. Корректен ли код Agent Runtime
4. Есть ли доступ к файлам и директориям

---

### Проблема 3: Нет прав на запись логов или доступ к файлам

**Причина**: Задача запускается от имени SYSTEM, могут быть проблемы с правами доступа.

**Решение**:

**Вариант A**: Изменить пользователя на доменную учетную запись с правами администратора:

```powershell
# Удалить текущую задачу
Unregister-ScheduledTask -TaskName "Portal Agent Runtime" -Confirm:$false

# Создать новую задачу с другим пользователем
$principal = New-ScheduledTaskPrincipal `
    -UserId "DOMAIN\USERNAME" `  # Замените на вашего пользователя
    -LogonType Password `
    -RunLevel Highest

# Пересоздать задачу с новым principal
$action = New-ScheduledTaskAction `
    -Execute "C:\inetpub\portal\.venv\Scripts\python.exe" `
    -Argument "-m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300" `
    -WorkingDirectory "C:\inetpub\portal"

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName "Portal Agent Runtime" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "AI Agent Runtime for Corporate Portal" `
    -Force
```

**Вариант B**: Добавить права на директории для пользователя SYSTEM:

```powershell
# Добавить полные права для SYSTEM на директорию проекта
$acl = Get-Acl "C:\inetpub\portal"
$accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "SYSTEM",
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$acl.SetAccessRule($accessRule)
Set-Acl "C:\inetpub\portal" $acl

# Добавить права на .venv директорию
$acl = Get-Acl "C:\inetpub\portal\.venv"
$accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "SYSTEM",
    "FullControl",
    "ContainerInherit,ObjectInherit",
    "None",
    "Allow"
)
$acl.SetAccessRule($accessRule)
Set-Acl "C:\inetpub\portal\.venv" $acl
```

---

### Проблема 4: Задача запускается, но Agent Runtime не отвечает

**Причина**: Возможно, процесс запустился, но работает некорректно.

**Решение**:

```powershell
# 1. Проверить, запущен ли процесс
$process = Get-Process python | Where-Object {$_.CommandLine -like "*uvicorn*agent_runtime*"}
if ($process) {
    Write-Host "Процесс найден: PID $($process.Id)"
    Write-Host "Команда: $($process.CommandLine)"
} else {
    Write-Host "Процесс не найден"
}

# 2. Проверить порт
$connection = Test-NetConnection -ComputerName 127.0.0.1 -Port 8090 -WarningAction SilentlyContinue
if ($connection.TcpTestSucceeded) {
    Write-Host "Порт 8090 доступен"
} else {
    Write-Host "Порт 8090 недоступен"
}

# 3. Попробовать вызвать health endpoint
try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" -TimeoutSec 5
    Write-Host "Health endpoint отвечает:"
    $response | ConvertTo-Json
} catch {
    Write-Host "Health endpoint недоступен: $($_.Exception.Message)"
}

# 4. Проверить историю задачи
Write-Host ""
Write-Host "История задачи:"
Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" |
    Where-Object {$_.Message -like "*Portal Agent Runtime*"} |
    Select-Object TimeCreated, Id, LevelDisplayName |
    Sort-Object TimeCreated -Descending |
    Select-Object -First 10
```

---

## Сравнение с Windows Service (NSSM)

| Характеристика | Task Scheduler | Windows Service (NSSM) |
|----------------|----------------|------------------------|
| **Автозапуск при старте** | ✅ Да | ✅ Да |
| **Перезапуск при сбоях** | ⚠️ Ограничен (до 10 раз) | ✅ Полный (бесконечно) |
| **Легкость настройки** | ✅ Очень легко (GUI + PowerShell) | ⚠️ Средне (только PowerShell) |
| **Требует установки** | ✅ Нет (встроен в Windows) | ❌ NSSM (чужеродный софт) |
| **Стабильность** | ⚠️ Средняя | ✅ Высокая |
| **Управление через Services.msc** | ❌ Нет | ✅ Да |
| **Логирование** | ⚠️ Базовое (Task Scheduler логи) | ✅ Расширенное |
| **Интеграция с Windows** | ✅ Полная | ✅ Полная |
| **Поддержка пользователей** | ✅ Часто задаваемые вопросы | ⚠️ Меньше информации |

### Когда использовать Task Scheduler:

✅ **Используйте Task Scheduler, если:**
- Хотите встроенное решение без установки дополнительных программ
- Достаточно базового автозапуска и ограниченного перезапуска
- Нужна легкая настройка через GUI
- Задача не критична для непрерывной работы

❌ **Не используйте Task Scheduler, если:**
- Нужна максимальная стабильность и надежность
- Требуется бесконечный автоматический перезапуск
- Нужен полный контроль над службой через Services.msc
- Задача критически важна для бизнеса

### Когда использовать Windows Service (NSSM):

✅ **Используйте NSSM (Windows Service), если:**
- Нужна максимальная стабильность работы
- Требуется надежный и бесконечный перезапуск при сбоях
- Хотите управление через Services.msc
- Задача критически важна для бизнеса
- Нужно расширенное логирование

❌ **Не используйте NSSM, если:**
- Не хотите устанавливать сторонние программы
- Достаточно базового автозапуска
- Не нужен полный контроль над службой

---

## Рекомендация для вашего проекта

### Для проекта "Корпоративный портал ВОБ №3":

**Рекомендую использовать Task Scheduler**, потому что:
1. ✅ Встроен в Windows, не требует установки
2. ✅ Достаточно для работы AI-агента (не критично для бизнеса)
3. ✅ Легко настраивается и отлаживается
4. ✅ Легко можно изменить настройки в будущем
5. ✅ Поддержка пользователей лучше (много документации)

**Если в будущем потребуется большая надежность**, можно будет мигрировать на Windows Service (NSSM).

---

## Полный скрипт проверки и настройки

```powershell
# ========================================
# ПОЛНЫЙ СКРИПТ ПРОВЕРКИ И НАСТРОЙКИ
# ========================================

Write-Host "===== НАСТРОЙКА AGENT RUNTIME ЧЕРЕZ TASK SCHEDULER =====" -ForegroundColor Cyan
Write-Host ""

# Проверка прав администратора
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "❌ Ошибка: Этот скрипт должен быть запущен от имени администратора!" -ForegroundColor Red
    Write-Host "Запустите PowerShell от имени администратора и попробуйте снова." -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Проверка прав администратора: Пройдена" -ForegroundColor Green
Write-Host ""

# Проверка существования файла Python
$pythonPath = "C:\inetpub\portal\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Host "❌ Ошибка: Python не найден по пути: $pythonPath" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Проверка Python: Пройдена" -ForegroundColor Green
Write-Host ""

# Проверка существования директории проекта
$projectDir = "C:\inetpub\portal"
if (-not (Test-Path $projectDir)) {
    Write-Host "❌ Ошибка: Директория проекта не найдена: $projectDir" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Проверка директории проекта: Пройдена" -ForegroundColor Green
Write-Host ""

# Проверка наличия задачи
$taskName = "Portal Agent Runtime"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "⚠️ Задача '$taskName' уже существует" -ForegroundColor Yellow
    Write-Host "Статус: $($existingTask.State)" -ForegroundColor Cyan
    Write-Host ""
    $response = Read-Host "Хотите удалить и пересоздать задачу? (y/N)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        Write-Host "Удаление существующей задачи..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "✅ Задача удалена" -ForegroundColor Green
    } else {
        Write-Host "❌ Отмена операции" -ForegroundColor Red
        exit 0
    }
}

Write-Host "Создание задачи..." -ForegroundColor Yellow
Write-Host ""

# Создание действия
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "-m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300" `
    -WorkingDirectory $projectDir

# Создание триггера
$trigger = New-ScheduledTaskTrigger -AtStartup

# Создание настроек безопасности
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Создание настроек задачи
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StopIfGoingOnBatteries $false `
    -DisallowStartOnRemoteAppSession $false

# Регистрация задачи
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "AI Agent Runtime for Corporate Portal - runs on port 8090" `
        -Force

    Write-Host "✅ Задача '$taskName' успешно создана!" -ForegroundColor Green
} catch {
    Write-Host "❌ Ошибка при создании задачи: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "===== ПРОВЕРКА СОЗДАННОЙ ЗАДАЧИ =====" -ForegroundColor Cyan
Write-Host ""

# Проверка задачи
$task = Get-ScheduledTask -TaskName $taskName
Write-Host "Имя: $($task.TaskName)"
Write-Host "Статус: $($task.State)"
Write-Host "Описание: $($task.Description)"
Write-Host ""

# Запуск задачи
Write-Host "Запуск задачи..." -ForegroundColor Yellow
try {
    Start-ScheduledTask -TaskName $taskName
    Write-Host "✅ Задача запущена" -ForegroundColor Green
} catch {
    Write-Host "❌ Ошибка при запуске задачи: $($_.Exception.Message)" -ForegroundColor Red
}

# Ожидание запуска
Write-Host ""
Write-Host "Ожидание запуска Agent Runtime..." -ForegroundColor Yellow
Write-Host "Пожалуйста, подождите 10 секунд..." -ForegroundColor Gray
Start-Sleep -Seconds 10

Write-Host ""
Write-Host "===== ПРОВЕРКА РАБОТЫ AGENT RUNTIME =====" -ForegroundColor Cyan
Write-Host ""

# Проверка процесса
Write-Host "1. Проверка процесса..." -ForegroundColor Yellow
$process = Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*uvicorn*agent_runtime*"}
if ($process) {
    Write-Host "   ✅ Процесс найден: PID $($process.Id)" -ForegroundColor Green
} else {
    Write-Host "   ❌ Процесс не найден" -ForegroundColor Red
}

# Проверка порта
Write-Host "2. Проверка порта 8090..." -ForegroundColor Yellow
$connection = Test-NetConnection -ComputerName 127.0.0.1 -Port 8090 -WarningAction SilentlyContinue
if ($connection.TcpTestSucceeded) {
    Write-Host "   ✅ Порт 8090 доступен" -ForegroundColor Green
} else {
    Write-Host "   ❌ Порт 8090 недоступен" -ForegroundColor Red
}

# Проверка health endpoint
Write-Host "3. Проверка health endpoint..." -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" -TimeoutSec 5
    Write-Host "   ✅ Health endpoint доступен" -ForegroundColor Green
    Write-Host "   Статус: $($response.status)" -ForegroundColor Cyan
    Write-Host "   Модель: $($response.model)" -ForegroundColor Cyan
    Write-Host "   Gateway: $($response.gateway_url)" -ForegroundColor Cyan
} catch {
    Write-Host "   ❌ Health endpoint недоступен: $($_.Exception.Message)" -ForegroundColor Red
}

# Проверка статуса задачи
Write-Host "4. Проверка статуса задачи..." -ForegroundColor Yellow
$task = Get-ScheduledTask -TaskName $taskName
Write-Host "   Статус: $($task.State)" -ForegroundColor Cyan
Write-Host "   Последний запуск: $($task.LastRunTime)" -ForegroundColor Cyan
Write-Host "   Следующий запуск: $($task.NextRunTime)" -ForegroundColor Cyan

Write-Host ""
Write-Host "===== ИНСТРУКЦИЯ ПО УПРАВЛЕНИЮ =====" -ForegroundColor Cyan
Write-Host ""
Write-Host "Команды PowerShell:" -ForegroundColor Yellow
Write-Host "  Запустить:     Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Gray
Write-Host "  Остановить:     Stop-ScheduledTask -TaskName '$taskName'" -ForegroundColor Gray
Write-Host "  Проверить:      Get-ScheduledTask -TaskName '$taskName'" -ForegroundColor Gray
Write-Host "  Удалить:       Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false" -ForegroundColor Gray
Write-Host ""
Write-Host "Графический интерфейс:" -ForegroundColor Yellow
Write-Host "  1. Откройте Task Scheduler: taskschd.msc" -ForegroundColor Gray
Write-Host "  2. Найдите задачу: $taskName" -ForegroundColor Gray
Write-Host "  3. Управляйте через контекстное меню (правая кнопка мыши)" -ForegroundColor Gray
Write-Host ""
Write-Host "Проверка работы:" -ForegroundColor Yellow
Write-Host "  AI-чат: http://localhost/ai/chat/" -ForegroundColor Gray
Write-Host "  Health:  http://127.0.0.1:8090/health" -ForegroundColor Gray
Write-Host ""

Write-Host "===== ЗАВЕРШЕНИЕ =====" -ForegroundColor Green
Write-Host "✅ Настройка завершена!" -ForegroundColor Green
Write-Host ""
Write-Host "Рекомендуется:" -ForegroundColor Yellow
Write-Host "1. Перезагрузить сервер для проверки автоматического запуска" -ForegroundColor Gray
Write-Host "2. После перезагрузки проверить работу AI-чата" -ForegroundColor Gray
Write-Host "3. Если есть проблемы, проверить логи в Task Scheduler" -ForegroundColor Gray
Write-Host ""
```

---

## Быстрые команды

### Проверка статуса:
```powershell
Get-ScheduledTask -TaskName "Portal Agent Runtime"
```

### Запуск задачи:
```powershell
Start-ScheduledTask -TaskName "Portal Agent Runtime"
```

### Остановка задачи:
```powershell
Stop-ScheduledTask -TaskName "Portal Agent Runtime"
```

### Проверка порта:
```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 8090
```

### Проверка health endpoint:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8090/health"
```

### Удаление задачи:
```powershell
Unregister-ScheduledTask -TaskName "Portal Agent Runtime" -Confirm:$false
```

---

## Контакты и поддержка

Если у вас возникли проблемы при настройке:

1. Проверьте этот документ на наличие решения вашей проблемы
2. Посмотрите логи Task Scheduler
3. Убедитесь, что Python и все зависимости установлены
4. Проверьте права доступа к директориям

---

## Заключение

Task Scheduler - отличный выбор для автоматического запуска Agent Runtime в вашем проекте. Он:
- ✅ Не требует установки дополнительного софта
- ✅ Легко настраивается
- ✅ Достаточно надежен для работы AI-агента
- ✅ Имеет хорошую документацию и поддержку

**Следующие шаги:**
1. Выполните настройку по инструкции выше
2. Перезагрузите сервер
3. Проверьте автоматический запуск
4. Протестируйте работу AI-чата

Удачи! 🚀
