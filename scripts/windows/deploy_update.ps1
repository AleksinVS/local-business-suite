# Deploy Portal Update
# Обновляет код на работающем IIS-хосте: collectstatic, копирует critical assets,
# перезапускает AppPool. Используется для регулярного деплоя изменений.
#
# Использование:
#   .\deploy_update.ps1
#   .\deploy_update.ps1 -SkipIISRestart
#   .\deploy_update.ps1 -VenvPath "C:\inetpub\portal\.venv\Scripts\python.exe"
#
# Что делает:
#   1. Выполняет collectstatic (собирает статику в staticfiles/)
#   2. Копирует критические пакеты (htmx) из staticfiles/ в static/ для IIS
#   3. Мягко перезапускает AppPool (без сброса соединений)
#   4. Проверяет доступность /health
#
# Предупреждение: перед запуском убедитесь, что код обновлён (git pull или бандл).

[CmdletBinding()]
param(
    [string]$PortalRoot = "C:\inetpub\portal",
    [string]$AppPoolName = "portal",
    [string]$VenvPath = "",  # пусто → автопоиск в .venv\Scripts\python.exe
    [switch]$SkipIISRestart,
    [switch]$SkipHealthCheck
)

$ErrorActionPreference = "Stop"

# --- Самоподъём до администратора --------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "Требуются права администратора. Перезапускаю с повышением..." -ForegroundColor Yellow
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    foreach ($key in $PSBoundParameters.Keys) {
        $val = $PSBoundParameters[$key]
        if ($val -is [switch]) {
            if ($val.IsPresent) { $argList += "-$key" }
        } else {
            $argList += "-$key", "`"$val`"" }
        }
    }
    $proc = Start-Process -FilePath "powershell" -ArgumentList $argList -Verb RunAs -Wait -PassThru
    exit $proc.ExitCode
}

# --- Утилиты -----------------------------------------------------------------
function Write-Step([string]$name) {
    Write-Host ""
    Write-Host "[$name]" -ForegroundColor Cyan
}
function Write-Ok([string]$msg) {
    Write-Host "  OK  $msg" -ForegroundColor Green
}
function Write-Skip([string]$msg) {
    Write-Host "  -   $msg" -ForegroundColor Gray
}
function Write-Warn([string]$msg) {
    Write-Host "  !   $msg" -ForegroundColor Yellow
}

Write-Host "=== Deploy Portal Update ===" -ForegroundColor Cyan
Write-Host ""

if ($PortalRoot.EndsWith("\")) { $PortalRoot = $PortalRoot.TrimEnd("\") }
Set-Location $PortalRoot

# --- Найти Python ------------------------------------------------------------
if (-not $VenvPath) {
    $venvPython = Join-Path $PortalRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $VenvPath = $venvPython
    } else {
        Write-Host "ОШИБКА: Python не найдён (.venv\Scripts\python.exe)" -ForegroundColor Red
        exit 1
    }
}
Write-Ok "Python: $VenvPath"

# --- 1. Collectstatic ---------------------------------------------------------
Write-Step "Collectstatic"
& $VenvPath manage.py collectstatic --no-input
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Collectstatic выполнен"
} else {
    Write-Host "ОШИБКА: collectstatic завершился с кодом $LASTEXITCODE" -ForegroundColor Red
    exit 1
}

# --- 2. Скопировать критические пакеты (htmx) -------------------------------
Write-Step "Копирование критических пакетов (htmx)"
$packagesToSync = @(
    "django_htmx"
)

$totalCopied = 0
foreach ($package in $packagesToSync) {
    $sourceDir = Join-Path $PortalRoot "staticfiles\$package"
    $targetDir = Join-Path $PortalRoot "static\$package"

    if (Test-Path $sourceDir) {
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }

        $files = Get-ChildItem -Path $sourceDir -File
        $copied = 0
        foreach ($file in $files) {
            $targetPath = Join-Path $targetDir $file.Name
            Copy-Item -Path $file.FullName -Destination $targetPath -Force
            $copied++
        }
        Write-Ok "$package : скопировано $copied файлов"
        $totalCopied += $copied
    } else {
        Write-Warn "$package : исходная папка не найдена (staticfiles\$package)"
    }
}

if ($totalCopied -eq 0) {
    Write-Warn "Ни один файл не был скопирован (пакеты могут отсутствовать)"
}

# --- 3. Перезапуск AppPool -----------------------------------------------
if (-not $SkipIISRestart) {
    Write-Step "Перезапуск AppPool"
    try {
        Import-Module WebAdministration
        Restart-WebAppPool -Name $AppPoolName -ErrorAction Stop
        Write-Ok "AppPool '$AppPoolName' перезапущен"

        # Небольшая пауза для полного перезапуска
        Start-Sleep -Seconds 2
    } catch {
        Write-Host "ОШИБКА: не удалось перезапустить AppPool: $_" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Skip "Перезапуск AppPool пропущен (SkipIISRestart)"
}

# --- 4. Проверка здоровья ---------------------------------------------------
if (-not $SkipHealthCheck) {
    Write-Step "Проверка здоровья"

    $tries = 0
    $maxTries = 10
    $success = $false

    while (-not $success -and $tries -lt $maxTries) {
        $tries++
        try {
            $response = Invoke-WebRequest -Uri "http://localhost/health" -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                Write-Ok "Health-check OK (код 200)"
                $success = $true
            }
        } catch {
            Write-Host "  Попытка $tries/$maxTries : не удалось подключиться к /health" -ForegroundColor Gray
            Start-Sleep -Seconds 2
        }
    }

    if (-not $success) {
        Write-Host "ОШИБКА: health-check не прошёл после $maxTries попыток" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Skip "Проверка здоровья пропущена (SkipHealthCheck)"
}

Write-Host ""
Write-Host "=== Деплой завершён ===" -ForegroundColor Green
Write-Host "Следующие шаги:"
Write-Host "  1. Откройте сайт в браузере (Ctrl+F5 для сброса кэша)"
Write-Host "  2. Проверьте, что кнопка 'Создать заявку' открывает форму"
