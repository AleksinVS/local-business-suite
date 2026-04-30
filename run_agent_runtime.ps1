# Запуск Agent Runtime в фоновом режиме
# Используйте этот скрипт для временного запуска без создания Windows Service
# Uses relative paths to be deployment-agnostic

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Запуск Agent Runtime..." -ForegroundColor Green
Write-Host "Рабочая директория: $scriptPath" -ForegroundColor Cyan

cd $scriptPath

# Проверка порта
$port = 8090
$connection = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue
if ($connection.TcpTestSucceeded) {
    Write-Host "ВНИМАНИЕ: Порт $port уже занят!" -ForegroundColor Yellow
    Write-Host "Остановите существующий процесс или измените порт." -ForegroundColor Yellow
    exit 1
}

# Запуск в фоновом задании
$job = Start-Job -ScriptBlock {
    $scriptPath = $using:scriptPath
    $env:PYTHONUNBUFFERED = "1"
    cd $scriptPath
    & ".\.venv\Scripts\python.exe" -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 -timeout-keep-alive 300
}

Write-Host "Agent Runtime запущен в фоновом режиме (Job ID: $($job.Id))" -ForegroundColor Green
Write-Host "Ожидание запуска сервера..." -ForegroundColor Yellow

# Ожидание запуска
$maxWait = 30
$waited = 0
while ($waited -lt $maxWait) {
    Start-Sleep -Seconds 2
    $waited += 2
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" -ErrorAction Stop
        Write-Host "✓ Agent Runtime успешно запущен!" -ForegroundColor Green
        Write-Host "  Статус: $($response.status)" -ForegroundColor Cyan
        Write-Host "  Модель: $($response.model)" -ForegroundColor Cyan
        Write-Host "  Gateway: $($response.gateway_url)" -ForegroundColor Cyan
        Write-Host "  API ключ настроен: $($response.openai_key_configured)" -ForegroundColor Cyan
        break
    } catch {
        Write-Host "  Ожидание... ($waited/$maxWait сек)" -ForegroundColor Gray
    }
}

if ($waited -ge $maxWait) {
    Write-Host "ОШИБКА: Agent Runtime не запустился за $maxWait секунд" -ForegroundColor Red
    Write-Host "Проверьте логи:" -ForegroundColor Yellow
    Receive-Job -Id $job.Id | Select-Object -Last 20
    exit 1
}

Write-Host ""
Write-Host "Управление:" -ForegroundColor Yellow
Write-Host "  Проверить статус: Get-Job -Id $($job.Id)" -ForegroundColor Gray
Write-Host "  Остановить: Stop-Job -Id $($job.Id)" -ForegroundColor Gray
Write-Host "  Удалить: Remove-Job -Id $($job.Id)" -ForegroundColor Gray
Write-Host ""
Write-Host "Health endpoint: http://127.0.0.1:8090/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "Нажмите Ctrl+C для остановки или закройте это окно" -ForegroundColor Yellow

# Держать скрипт работающим
try {
    while ($job.State -eq "Running") {
        Start-Sleep -Seconds 5
    }
} finally {
    Write-Host ""
    Write-Host "Остановка Agent Runtime..." -ForegroundColor Yellow
    Stop-Job -Id $job.Id
    Remove-Job -Id $job.Id
    Write-Host "Agent Runtime остановлен" -ForegroundColor Green
}
