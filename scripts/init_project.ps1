# Project Initialization Script for IIS Deployment
# Скрипт создает необходимые директории для работы проекта

$ErrorActionPreference = "Stop"

Write-Host "=== Project Initialization for IIS ===" -ForegroundColor Cyan
Write-Host ""

$projectDir = "C:\inetpub\portal"

# Проверка директории проекта
if (-not (Test-Path $projectDir)) {
    Write-Host "ОШИБКА: Директория проекта не найдена: $projectDir" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Директория проекта найдена: $projectDir" -ForegroundColor Green
Write-Host ""

# Создание необходимых директорий
Write-Host "Создание директорий..." -ForegroundColor Yellow

$directories = @(
    "logs",
    "media",
    "db",
    "staticfiles"
)

$createdDirs = 0
foreach ($dir in $directories) {
    $dirPath = Join-Path $projectDir $dir
    if (-not (Test-Path $dirPath)) {
        try {
            New-Item -ItemType Directory -Path $dirPath -Force | Out-Null
            Write-Host "  ✓ Создана: $dir/" -ForegroundColor Green
            $createdDirs++
        } catch {
            Write-Host "  ✗ Ошибка создания $dir: $($_.Exception.Message)" -ForegroundColor Red
        }
    } else {
        Write-Host "  - Уже существует: $dir/" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Создано директорий: $createdDirs из $($directories.Count)" -ForegroundColor Cyan
Write-Host ""

# Установка прав доступа для IIS
Write-Host "Настройка прав доступа..." -ForegroundColor Yellow

try {
    # Проверка существования IIS AppPool
    $appPool = "IIS AppPool\DefaultAppPool"
    
    # Установка прав для logs
    $logsDir = Join-Path $projectDir "logs"
    if (Test-Path $logsDir) {
        icacls $logsDir /grant "$appPool:(OI)(CI)M" /T | Out-Null
        Write-Host "  ✓ Права настроены: logs/" -ForegroundColor Green
    }
    
    # Установка прав для media
    $mediaDir = Join-Path $projectDir "media"
    if (Test-Path $mediaDir) {
        icacls $mediaDir /grant "$appPool:(OI)(CI)M" /T | Out-Null
        Write-Host "  ✓ Права настроены: media/" -ForegroundColor Green
    }
    
    # Установка прав для db
    $dbDir = Join-Path $projectDir "db"
    if (Test-Path $dbDir) {
        icacls $dbDir /grant "$appPool:(OI)(CI)M" /T | Out-Null
        Write-Host "  ✓ Права настроены: db/" -ForegroundColor Green
    }
    
} catch {
    Write-Host "  ⚠ Предупреждение: Не удалось настроить права: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Инициализация завершена ===" -ForegroundColor Green
Write-Host ""
Write-Host "Результаты:" -ForegroundColor Cyan
Write-Host "✓ Директории созданы" -ForegroundColor Green
Write-Host "✓ Права доступа настроены" -ForegroundColor Green
Write-Host ""
Write-Host "Далее:" -ForegroundColor Yellow
Write-Host "1. Выполните миграции:" -ForegroundColor White
Write-Host "   python manage.py migrate" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Соберите статику:" -ForegroundColor White
Write-Host "   python manage.py collectstatic --noinput" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Перезагрузите IIS:" -ForegroundColor White
Write-Host "   iisreset /restart" -ForegroundColor Gray
Write-Host ""
Write-Host "✓ Проект готов к работе!" -ForegroundColor Green
