# Prepare Target Host for Portal Import
# Скрипт выполняет подготовительные работы на целевом хосте Windows 10 Pro
# перед импортом Portal из бандла export_portal.ps1.
#
# Назначение: проверить и подготовить новый хост для миграции Portal
#
# Использование:
#   .\prepare_target_host.ps1
#   .\prepare_target_host.ps1 -PythonPath "C:\Program Files\Python311\python.exe"
#   .\prepare_target_host.ps1 -ExpectedDomain "mscher.local" -TargetHostname "stc-web2"
#   .\prepare_target_host.ps1 -InstallPython -PythonInstaller "C:\temp\python-3.11.0-amd64.exe"
#
# Что делает:
#   1. Проверяет/устанавливает Python 3.11
#   2. Проверяет членство в домене и доступность LDAP
#   3. Включает IIS и необходимые компоненты
#   4. Создаёт структуру каталогов C:\inetpub\portal
#   5. Проверяет доступность портов 80/443
#   6. Генерирует отчёт готовности к импорту

[CmdletBinding()]
param(
    [string]$PythonPath = "C:\Program Files\Python311\python.exe",
    [string]$ExpectedDomain,
    [string]$TargetHostname,
    [string]$PythonInstaller,
    [string]$PortalRoot = "C:\inetpub\portal",
    [switch]$InstallPython,
    [switch]$SkipDomainCheck,
    [switch]$SkipIISCheck,
    [switch]$SkipPythonCheck,
    [switch]$SkipPortCheck
)

$ErrorActionPreference = "Stop"

# --- Самоподъём до администратора --------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Требуются права администратора. Перезапускаю с повышением..." -ForegroundColor Yellow
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    foreach ($key in $PSBoundParameters.Keys) {
        $val = $PSBoundParameters[$key]
        if ($val -is [switch]) {
            if ($val.IsPresent) { $argList += "-$key" }
        } else {
            $argList += "-$key", "`"$val`""
        }
    }
    $proc = Start-Process -FilePath "powershell" -ArgumentList $argList -Verb RunAs -Wait -PassThru
    exit $proc.ExitCode
}

Write-Host "=== Подготовка целевого хоста к импорту Portal ===" -ForegroundColor Cyan
Write-Host ""

# --- Утилиты -----------------------------------------------------------------
function Write-Step($name) { Write-Host ""; Write-Host "[$name]" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  !   $msg" -ForegroundColor Yellow }
function Write-Skip($msg)  { Write-Host "  -   $msg" -ForegroundColor Gray }
function Write-Fail($msg)  { Write-Host "  X   $msg" -ForegroundColor Red }

$issues = @()
$warnings = @()

# --- Сводка системы ------------------------------------------------------------
Write-Step "Сводка системы"

$osInfo = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem

Write-Host "  ОС: $($osInfo.Caption)" -ForegroundColor Gray
Write-Host "  Версия: $($osInfo.Version)" -ForegroundColor Gray
Write-Host "  Хостname: $($env:COMPUTERNAME)" -ForegroundColor Gray
if ($cs.PartOfDomain) {
    Write-Host "  Домен: $($cs.Domain)" -ForegroundColor Green
} else {
    Write-Host "  Домен: не введён в домен" -ForegroundColor Yellow
    $warnings += "Хост НЕ введён в домен — LDAP/Kerberos и UNC-шары работать не будут"
}

if ($TargetHostname -and $env:COMPUTERNAME -ne $TargetHostname) {
    Write-Warn "Запрошенное имя '$TargetHostname' не совпадает с текущим '$($env:COMPUTERNAME)'"
    $warnings += "Уточните -TargetHostname или переименуйте хост перед импортом"
}

# --- Проверка Python ---------------------------------------------------------
Write-Step "Python 3.11"

if ($SkipPythonCheck) {
    Write-Skip "пропущено (SkipPythonCheck)"
} else {
    if (Test-Path $PythonPath) {
        Write-Ok "Python найдён: $PythonPath"
        try {
            $version = & $PythonPath -c "import sys; print(sys.version.split()[0])" 2>$null
            Write-Host "  Версия: $version" -ForegroundColor Gray
            if (-not $version.StartsWith("3.11")) {
                Write-Warn "версия не 3.11 — возможны проблемы совместимости"
                $warnings += "Python версии не 3.11"
            }
        } catch {
            Write-Fail "Python не запускается: $($_.Exception.Message)"
            $issues += "Python не работоспособен"
        }
    } else {
        Write-Fail "Python не найден по пути: $PythonPath"
        if ($InstallPython -and $PythonInstaller) {
            Write-Host "  Путь к инсталлятору: $PythonInstaller" -ForegroundColor Gray
            if (Test-Path $PythonInstaller) {
                Write-Host "  Установка Python... (может занять время)" -ForegroundColor Yellow
                try {
                    $proc = Start-Process -FilePath $PythonInstaller -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=0" -Wait -PassThru
                    if ($proc.ExitCode -eq 0) {
                        Write-Ok "Python установлен"
                    } else {
                        Write-Fail "установка завершилась с кодом $($proc.ExitCode)"
                        $issues += "Python не установлен"
                    }
                } catch {
                    Write-Fail "ошибка запуска инсталлятора: $($_.Exception.Message)"
                    $issues += "Не удалось установить Python"
                }
            } else {
                Write-Fail "инсталлятор не найден: $PythonInstaller"
                $issues += "Инсталлятор Python не найден"
            }
        } else {
            Write-Warn "Укажите -InstallPython -PythonInstaller <путь> для автоустановки"
            $issues += "Python не установлен"
        }
    }
}

# --- Проверка домена и LDAP -------------------------------------------------
Write-Step "Домен и LDAP"

if ($SkipDomainCheck) {
    Write-Skip "пропущено (SkipDomainCheck)"
} else {
    if ($cs.PartOfDomain) {
        Write-Ok "хост введён в домен: $($cs.Domain)"
        if ($ExpectedDomain -and $cs.Domain -ne $ExpectedDomain) {
            Write-Warn "ожидаемый домен '$ExpectedDomain' не совпадает с текущим '$($cs.Domain)'"
            $warnings += "Домен не совпадает с ожидаемым"
        }

        # Проверка доступности LDAP
        $ldapServer = $cs.Domain
        if ($ExpectedDomain) { $ldapServer = $ExpectedDomain }

        # Попробуем найти DC
        try {
            $domainRole = Get-CimInstance Win32_ComputerSystem | Select-Object -ExpandProperty DomainRole
            if ($domainRole -ne 0) { # 0 = Standalone
                # Пробуем разрешить имя домена в DC
                $ldapTarget = $ldapServer
                # Проверяем порты 389 и 636
                $ldapOk = $true
                foreach ($port in @(389, 636)) {
                    try {
                        $r = Test-NetConnection -ComputerName $ldapTarget -Port $port -WarningAction SilentlyContinue -InformationLevel Quiet
                        if ($r.TcpTestSucceeded) {
                            Write-Ok "LDAP ${ldapTarget}:$port доступен"
                        } else {
                            Write-Fail "LDAP ${ldapTarget}:$port НЕ доступен"
                            $ldapOk = $false
                        }
                    } catch {
                        Write-Fail "проверка LDAP ${ldapTarget}:$port не выполнена"
                        $ldapOk = $false
                    }
                }
                if (-not $ldapOk) {
                    $issues += "LDAP недоступен — аутентификация доменных пользователей работать не будет"
                }
            }
        } catch {
            Write-Warn "не удалось определить роль хоста в домене: $($_.Exception.Message)"
        }
    } else {
        Write-Fail "хост НЕ введён в домен"
        if ($ExpectedDomain) {
            Write-Host "  Ожидали: $ExpectedDomain" -ForegroundColor Gray
        }
        $issues += "Хост не в домене — доменная аутентификация не будет работать"
        $warnings += "Если на источнике использовался доменный App Pool — нужны доменные учётки"
    }
}

# --- Проверка/включение IIS ---------------------------------------------------
Write-Step "IIS"

if ($SkipIISCheck) {
    Write-Skip "пропущено (SkipIISCheck)"
} else {
    $appcmd = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"

    if (-not (Test-Path $appcmd)) {
        Write-Fail "IIS не установлен (appcmd.exe не найден)"
        Write-Host "  Включение IIS..." -ForegroundColor Yellow
        try {
            if (Get-Command Install-WindowsFeature -ErrorAction SilentlyContinue) {
                # Windows Server
                Install-WindowsFeature -Name Web-Server -IncludeManagementTools | Out-Null
            } else {
                # Windows 10 Pro
                $features = @(
                    "IIS-WebServerRole", "IIS-WebServer", "IIS-CommonHttpFeatures",
                    "IIS-StaticContent", "IIS-DefaultDocument", "IIS-HttpErrors",
                    "IIS-RequestFiltering", "IIS-CGI",
                    "IIS-WebServerManagementTools", "IIS-ManagementConsole"
                )
                foreach ($f in $features) {
                    Enable-WindowsOptionalFeature -Online -FeatureName $f -NoRestart -ErrorAction Stop | Out-Null
                }
            }
            Write-Ok "IIS включён"
        } catch {
            Write-Fail "ошибка включения IIS: $($_.Exception.Message)"
            $issues += "IIS не установлен/не включён"
        }
    } else {
        Write-Ok "IIS установлен"

        # Проверка критических компонентов
        $hasInstallWindowsFeature = Get-Command Install-WindowsFeature -ErrorAction SilentlyContinue
        if ($hasInstallWindowsFeature) {
            # Windows Server
            $required = @("Web-Server", "Web-CGI", "Web-Static-Content")
            foreach ($f in $required) {
                $state = Get-WindowsFeature $f -ErrorAction SilentlyContinue
                if ($state -and -not $state.Installed) {
                    Write-Warn "$f не установлен — устанавливаю..."
                    Install-WindowsFeature -Name $f | Out-Null
                }
            }
        } else {
            # Windows 10 Pro
            $clientRequired = @("IIS-CGI")
            foreach ($f in $clientRequired) {
                $st = Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction SilentlyContinue
                if ($st -and $st.State -ne "Enabled") {
                    Write-Warn "$f не включён — включаю..."
                    Enable-WindowsOptionalFeature -Online -FeatureName $f -NoRestart -ErrorAction Stop | Out-Null
                }
            }
        }
        Write-Ok "критические IIS-компоненты включены"
    }
}

# --- Проверка портов ---------------------------------------------------------
Write-Step "Порты"

if ($SkipPortCheck) {
    Write-Skip "пропущено (SkipPortCheck)"
} else {
    $ports = @{80 = "HTTP"; 443 = "HTTPS"}
    foreach ($p in $ports.Keys) {
        $existing = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
        if ($existing) {
            $process = Get-Process -Id $existing.OwningProcess -ErrorAction SilentlyContinue
            if ($process) {
                Write-Host "  Порт $($p) $($ports[$p]): занят процессом $($process.ProcessName) (PID $($existing.OwningProcess))" -ForegroundColor Yellow
                if ($p -eq 80 -or $p -eq 443) {
                    if ($existing.OwningProcess -ne $PID) {
                        Write-Warn "порт $($p) занят не IIS — возможен конфликт"
                        $warnings += "Порт $($p) занят другим процессом"
                    }
                }
            }
        } else {
            Write-Ok "Порт $($p) $($ports[$p]): свободен"
        }
    }
}

# --- Создание структуры каталогов ------------------------------------------
Write-Step "Каталоги"

if (Test-Path $PortalRoot) {
    Write-Warn "$PortalRoot уже существует"
    if (-not (Test-Path (Join-Path $PortalRoot "manage.py"))) {
        Write-Fail "в $PortalRoot нет manage.py — это не директория Portal?"
        $issues += "Каталог PortalRoot существует, но не содержит manage.py"
    }
} else {
    try {
        New-Item -ItemType Directory -Path $PortalRoot -Force | Out-Null
        Write-Ok "создан $PortalRoot"
    } catch {
        Write-Fail "ошибка создания $PortalRoot : $($_.Exception.Message)"
        $issues += "Не удалось создать каталог PortalRoot"
    }
}

# --- Создание подкаталогов (для будущего импорта) --------------------
Write-Step "Структура Portal"

if (Test-Path $PortalRoot) {
    $subdirs = @("logs", "media", "db", "staticfiles")
    foreach ($dir in $subdirs) {
        $path = Join-Path $PortalRoot $dir
        if (-not (Test-Path $path)) {
            try {
                New-Item -ItemType Directory -Path $path -Force | Out-Null
                Write-Host "  создан: $dir\" -ForegroundColor Gray
            } catch {
                Write-Warn "не удалось создать $dir : $($_.Exception.Message)"
            }
        }
    }
    Write-Ok "структура каталогов готова"
}

# --- Финальный отчёт ------------------------------------------------------
Write-Step "Отчёт готовности"

Write-Host ""
if ($issues.Count -eq 0) {
    Write-Host "=== ГОТОВ К ИМПОРТУ ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Следующие шаги:" -ForegroundColor Cyan
    Write-Host "  1. Скопируйте архив экспорта на этот хост" -ForegroundColor White
    Write-Host "  2. Запустите:" -ForegroundColor White
    Write-Host "     .\import_portal.ps1 -BundlePath <путь-к-архиву> -NewHostname $($env:COMPUTERNAME)" -ForegroundColor Gray
    if ($cs.PartOfDomain -and -not $SkipDomainCheck) {
        Write-Host "     .\import_portal.ps1 -BundlePath <zip> -NewHostname $($env:COMPUTERNAME) -AppPoolUser 'DOMAIN\svc_portal' -AppPoolPassword '***'" -ForegroundColor Gray
    }
    Write-Host "  3. После импорта:" -ForegroundColor White
    Write-Host "     - Проверьте curl http://127.0.0.1:8090/health" -ForegroundColor Gray
    Write-Host "     - Откройте портал и проверьте чат ИИ" -ForegroundColor Gray
    Write-Host "     - Если нужен HTTPS — импортируйте сертификаты и настройте 443" -ForegroundColor Gray
} else {
    Write-Host "=== НЕ ГОТОВ К ИМПОРТУ ===" -ForegroundColor Red
    Write-Host ""
    Write-Host "Критичные проблемы ($($issues.Count)):" -ForegroundColor Red
    foreach ($issue in $issues) {
        Write-Host "  X  $issue" -ForegroundColor Red
    }
}

if ($warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "Предупреждения ($($warnings.Count)):" -ForegroundColor Yellow
    foreach ($warn in $warnings) {
        Write-Host "  !  $warn" -ForegroundColor Yellow
    }
    if ($issues.Count -eq 0) {
        Write-Host ""
        Write-Host "Импорт возможен, но могут быть проблемы с функциональностью." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Подготовка завершена ===" -ForegroundColor Cyan

# --- Код возврата ------------------------------------------------------------
if ($issues.Count -gt 0) {
    exit 1
} else {
    exit 0
}