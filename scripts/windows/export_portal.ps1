# Export Portal Configuration for Migration
# Снимает дамп конфигурации IIS, Scheduled Task, файрвола, сертификатов
# и копию кода проекта в отдельный каталог для переноса на другой хост.
#
# Назначение: штатная миграция portal между Windows-хостами
# (например, Windows Server 2022 -> Windows 10 Pro).
#
# Использование:
#   .\export_portal.ps1
#   .\export_portal.ps1 -OutputDir D:\migration
#   .\export_portal.ps1 -IncludeData -IncludeDb
#   .\export_portal.ps1 -IncludeEnv   # ВНИМАНИЕ: содержит секреты
#
# Что в выходном каталоге:
#   portal-export-<timestamp>\
#     manifest.json                 # снимок параметров исходного хоста
#     manifests\host.json           # детали хоста + список IIS-фич источника
#     iis\
#       applicationhost-backup\     # полный appcmd backup
#       site-<name>.xml             # конфиг сайта
#       apppool-<name>.xml          # конфиг пула (в т.ч. identityType/userName)
#       web.config                  # копия актуального web.config
#     tasks\
#       <taskname>.xml              # экспорт Scheduled Task (без BOM)
#     firewall\
#       portal-rules.json           # правила брандмауэра
#     certs\
#       cert-list.json              # только метаданные (НЕ приватные ключи)
#     source\                       # копия кода (без venv, .env, .local, data)

[CmdletBinding()]
param(
    [string]$OutputDir = ".\portal-export",
    [string]$PortalRoot = "C:\inetpub\portal",
    [string]$SiteName = "portal",
    [string]$AppPoolName = "portal",
    [string]$TaskName = "Portal Agent Runtime",
    [string]$TaskPath = "\Portal\",
    [switch]$IncludeData,    # включить data/ (контракты runtime, состояние)
    [switch]$IncludeDb,      # включить db/*.sqlite3*
    [switch]$IncludeEnv,     # включить .env (СЕКРЕТЫ — передавать защищённым каналом)
    [switch]$SkipIIS,
    [switch]$SkipTask,
    [switch]$SkipFirewall,
    [switch]$SkipCerts,
    [switch]$SkipSource,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Самоподъём до администратора, если запустили без прав
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

Write-Host "=== Export Portal Configuration ===" -ForegroundColor Cyan
Write-Host ""

# Фиксируем директорию скрипта как базовую (важно при самоподъёме администратора)
# Используем $PSCommandPath вместо $PSScriptRoot, т.к. при самоподъёме $PSScriptRoot меняется
$scriptRoot = Split-Path -Parent $PSCommandPath
if (-not $scriptRoot) { $scriptRoot = $PSScriptRoot }
Set-Location $scriptRoot
Write-Host "Working directory: $scriptRoot" -ForegroundColor Gray
Write-Host "Script path: $PSCommandPath" -ForegroundColor Gray

# --- Утилиты -----------------------------------------------------------------
function Write-Step($name) {
    Write-Host ""
    Write-Host "[$name]" -ForegroundColor Cyan
}
function Write-Ok($msg)     { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg)   { Write-Host "  !   $msg" -ForegroundColor Yellow }
function Write-Skip($msg)   { Write-Host "  -   $msg" -ForegroundColor Gray }

# Запись текста в UTF-8 БЕЗ BOM.
# BOM ломает Register-ScheduledTask -Xml и парсинг .env в python-dotenv.
function Write-Utf8NoBom([string]$path, [string]$content) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($path, $content, $enc)
}

# --- Нормализация путей ------------------------------------------------------
if ($PortalRoot.EndsWith("\")) { $PortalRoot = $PortalRoot.TrimEnd("\") }
if ($TaskPath -and -not $TaskPath.StartsWith("\")) { $TaskPath = "\$TaskPath" }
if ($TaskPath -and -not $TaskPath.EndsWith("\"))    { $TaskPath = "$TaskPath\" }
if (-not (Test-Path $PortalRoot)) {
    Write-Host "ОШИБКА: Корень проекта не найден: $PortalRoot" -ForegroundColor Red
    exit 1
}
$PortalRoot = (Resolve-Path $PortalRoot).Path
Write-Host "PortalRoot: $PortalRoot" -ForegroundColor Gray

# --- Куда пишем --------------------------------------------------------------
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bundleName = "portal-export-$timestamp"
# Делаем OutputDir абсолютным — важно при самоподъёме администратора
if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = $OutputRoot = (Resolve-Path $OutputDir).Path
} else {
    $OutputDir = Join-Path $scriptRoot $OutputDir.TrimStart(".\")
}
$bundleRoot = Join-Path $OutputDir $bundleName

# Создать родительскую директорию, если её нет
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

if (Test-Path $bundleRoot) {
    if (-not $Force) {
        Write-Host "ОШИБКА: Бандл уже существует: $bundleRoot" -ForegroundColor Red
        Write-Host "Используйте -Force для перезаписи." -ForegroundColor Yellow
        exit 1
    }
    Remove-Item -Path $bundleRoot -Recurse -Force
}

# Структура каталогов
$dirs = @{
    Iis       = Join-Path $bundleRoot "iis"
    Tasks     = Join-Path $bundleRoot "tasks"
    Firewall  = Join-Path $bundleRoot "firewall"
    Certs     = Join-Path $bundleRoot "certs"
    Source    = Join-Path $bundleRoot "source"
    Manifests = Join-Path $bundleRoot "manifests"
}
foreach ($d in $dirs.Values) {
    New-Item -ItemType Directory -Path $d -Force | Out-Null
}

# --- Сбор метаданных хоста ----------------------------------------------------
Write-Step "Снимок параметров хоста"

$osInfo = Get-CimInstance Win32_OperatingSystem

# FQDN может не резолвиться (обратный DNS) — не роняем экспорт из-за этого.
try {
    $fqdn = [System.Net.Dns]::GetHostEntry($env:COMPUTERNAME).HostName
} catch {
    $fqdn = $env:COMPUTERNAME
}

$hostInfo = [ordered]@{
    hostname           = $env:COMPUTERNAME
    fqdn                = $fqdn
    os_caption          = $osInfo.Caption
    os_version          = $osInfo.Version
    os_architecture     = $osInfo.OSArchitecture
    powershell_version  = $PSVersionTable.PSVersion.ToString()
    timestamp_utc       = (Get-Date).ToUniversalTime().ToString("o")
    bundle_name         = $bundleName
    portal_root         = $PortalRoot
    iis_site            = $SiteName
    iis_apppool         = $AppPoolName
    scheduled_task      = "$TaskPath$TaskName"
}

# Домен (важно для LDAP/Kerberos на целевом хосте)
try {
    $cs = Get-CimInstance Win32_ComputerSystem
    $hostInfo["part_of_domain"] = [bool]$cs.PartOfDomain
    if ($cs.PartOfDomain) { $hostInfo["domain"] = $cs.Domain }
} catch {}

# IIS версия
try {
    $iisVersion = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\InetStp\" -ErrorAction SilentlyContinue).MajorVersion
    if ($iisVersion) { $hostInfo["iis_version"] = "$iisVersion" }
} catch {}

# Список включённых IIS-компонентов источника.
# Имена на Server (Web-*) и на Windows 10 (IIS-*) не совпадают — сохраняем оба
# возможных представления, чтобы на целевом хосте было с чем сверять маппинг.
try {
    if (Get-Command Get-WindowsFeature -ErrorAction SilentlyContinue) {
        $srvFeatures = Get-WindowsFeature -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'Web-*' -and $_.Installed } |
            Select-Object -ExpandProperty Name
        $hostInfo["iis_features_server"] = @($srvFeatures)
    }
    if (Get-Command Get-WindowsOptionalFeature -ErrorAction SilentlyContinue) {
        $cliFeatures = Get-WindowsOptionalFeature -Online -ErrorAction SilentlyContinue |
            Where-Object { $_.FeatureName -like 'IIS-*' -and $_.State -eq 'Enabled' } |
            Select-Object -ExpandProperty FeatureName
        $hostInfo["iis_features_client"] = @($cliFeatures)
    }
} catch {
    Write-Warn "не удалось снять список IIS-фич: $($_.Exception.Message)"
}

# Python версии (system и venv)
$systemPython = Join-Path $env:ProgramFiles "Python311\python.exe"
if (Test-Path $systemPython) {
    $hostInfo["system_python"] = & $systemPython -c "import sys; print(sys.version.replace(chr(10),' '))" 2>$null
}
$venvPython = Join-Path $PortalRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $hostInfo["venv_python"] = & $venvPython -c "import sys; print(sys.version.replace(chr(10),' '))" 2>$null
}

# Сетевые адаптеры — IPv4
try {
    $addrs = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
             Where-Object { $_.IPAddress -ne "127.0.0.1" -and -not $_.InterfaceAlias.StartsWith("Loopback") } |
             Select-Object -ExpandProperty IPAddress
    $hostInfo["ipv4_addresses"] = @($addrs)
} catch {}

Write-Utf8NoBom (Join-Path $dirs.Manifests "host.json") ($hostInfo | ConvertTo-Json -Depth 5)
Write-Ok "host.json (включая список IIS-фич источника)"

# --- IIS: backup + экспорт сайта/пула ----------------------------------------
Write-Step "IIS"

if ($SkipIIS) {
    Write-Skip "пропущено (SkipIIS)"
} else {
    $appcmd = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"
    if (-not (Test-Path $appcmd)) {
        Write-Warn "appcmd.exe не найден — IIS не установлен или другая редакция ОС. Шаг IIS пропущен."
    } else {
        # Полный backup applicationHost.config
        $backupName = "portal-export-$timestamp"
        & $appcmd add backup $backupName | Out-Null
        $backupDir = Join-Path $env:SystemRoot "System32\inetsrv\backup\$backupName"
        if (Test-Path $backupDir) {
            Copy-Item -Path $backupDir -Destination (Join-Path $dirs.Iis "applicationhost-backup") -Recurse -Force
            Write-Ok "applicationhost backup скопирован"
        } else {
            Write-Warn "appcmd add backup не создал каталог $backupDir"
        }

        # Сайт
        $siteXmlPath = Join-Path $dirs.Iis "site-$SiteName.xml"
        & $appcmd list site "$SiteName" /config /xml > $siteXmlPath 2>$null
        if ((Test-Path $siteXmlPath) -and (Get-Item $siteXmlPath).Length -gt 0) {
            Write-Ok "site '$SiteName' -> site-$SiteName.xml"
        } else {
            Write-Warn "сайт '$SiteName' не найден или пустой конфиг"
        }

        # AppPool (сохраняем в т.ч. identityType/userName для восстановления на цели)
        $poolXmlPath = Join-Path $dirs.Iis "apppool-$AppPoolName.xml"
        & $appcmd list apppool "$AppPoolName" /config /xml > $poolXmlPath 2>$null
        if ((Test-Path $poolXmlPath) -and (Get-Item $poolXmlPath).Length -gt 0) {
            Write-Ok "apppool '$AppPoolName' -> apppool-$AppPoolName.xml"
            # Подсказка про identity: пароль appcmd не отдаёт.
            try {
                [xml]$pxml = Get-Content $poolXmlPath -Raw
                $pm = $pxml.SelectSingleNode("//processModel")
                if ($pm -and $pm.identityType -eq "SpecificUser") {
                    Write-Warn "пул работает под доменной учёткой '$($pm.userName)' — на цели передайте её пароль через -AppPoolPassword"
                }
            } catch {}
        } else {
            Write-Warn "пул '$AppPoolName' не найден или пустой конфиг"
        }

        # Handlers (для диагностики wfastcgi)
        $handlersXmlPath = Join-Path $dirs.Iis "handlers-wfastcgi.xml"
        & $appcmd list config -section:system.webServer/handlers /commit:apphost /xml > $handlersXmlPath 2>$null
        if ((Test-Path $handlersXmlPath) -and (Get-Item $handlersXmlPath).Length -gt 0) {
            Write-Ok "handlers -> handlers-wfastcgi.xml"
        }

        # web.config
        $webConfigPath = Join-Path $PortalRoot "web.config"
        if (Test-Path $webConfigPath) {
            Copy-Item -Path $webConfigPath -Destination (Join-Path $dirs.Iis "web.config") -Force
            Write-Ok "web.config скопирован"
        } else {
            Write-Warn "web.config отсутствует в $PortalRoot"
        }
    }
}

# --- Scheduled Task -----------------------------------------------------------
Write-Step "Scheduled Task"

if ($SkipTask) {
    Write-Skip "пропущено (SkipTask)"
} else {
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction Stop
        $xml = Export-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction Stop
        $xmlPath = Join-Path $dirs.Tasks "$TaskName.xml"
        # Без BOM — иначе Register-ScheduledTask -Xml на цели может отвергнуть файл.
        Write-Utf8NoBom $xmlPath (($xml -join "`r`n"))
        Write-Ok "$TaskPath$TaskName -> tasks\$TaskName.xml (без BOM)"
    } catch {
        $errMsg = $_.Exception.Message
        Write-Warn "Задача '$TaskPath$TaskName' не найдена или не экспортируется: $errMsg"
    }
}

# --- Firewall -----------------------------------------------------------------
Write-Step "Firewall"

if ($SkipFirewall) {
    Write-Skip "пропущено (SkipFirewall)"
} else {
    $portalRules = Get-NetFirewallRule -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -match 'Portal' -or $_.DisplayName -match 'IIS' }
    $out = @()
    foreach ($r in $portalRules) {
        $ports = (Get-NetFirewallPortFilter -AssociatedNetFirewallRule $r -ErrorAction SilentlyContinue).LocalPort
        $out += [ordered]@{
            display_name = $r.DisplayName
            display_id   = $r.DisplayName
            direction    = $r.Direction.ToString()
            action       = $r.Action.ToString()
            enabled      = $r.Enabled
            profile      = $r.Profile.ToString()
            local_port   = if ($ports) { @($ports) } else { @() }
        }
    }
    Write-Utf8NoBom (Join-Path $dirs.Firewall "portal-rules.json") ($out | ConvertTo-Json -Depth 5)
    Write-Ok "найдено $($out.Count) правил"
}

# --- Сертификаты (только метаданные) -----------------------------------------
Write-Step "Сертификаты (метаданные)"

if ($SkipCerts) {
    Write-Skip "пропущено (SkipCerts)"
} else {
    $certs = Get-ChildItem Cert:\LocalMachine\My -ErrorAction SilentlyContinue
    $out = @()
    foreach ($c in $certs) {
        $dnsNames = @()
        if ($c.Extensions) {
            foreach ($ext in $c.Extensions) {
                if ($ext.Oid.FriendlyName -eq "Subject Alternative Name") {
                    $san = $ext.Format(0) -split ","
                    foreach ($s in $san) {
                        if ($s -match "DNS Name=(.+)") { $dnsNames += $Matches[1].Trim() }
                    }
                }
            }
        }
        $out += [ordered]@{
            subject          = $c.Subject
            issuer           = $c.Issuer
            thumbprint       = $c.Thumbprint
            not_before       = $c.NotBefore.ToString("o")
            not_after        = $c.NotAfter.ToString("o")
            has_private_key  = $c.HasPrivateKey
            dns_names        = $dnsNames
            friendly_name    = $c.FriendlyName
        }
    }
    Write-Utf8NoBom (Join-Path $dirs.Certs "cert-list.json") ($out | ConvertTo-Json -Depth 5)
    Write-Ok "найдено $($out.Count) сертификатов в LocalMachine\My"
    Write-Warn "приватные ключи НЕ экспортированы — переносите их вручную защищённым каналом (.pfx)"
}

# --- Копия кода ---------------------------------------------------------------
Write-Step "Код проекта"

if ($SkipSource) {
    Write-Skip "пропущено (SkipSource)"
} else {
    # Если тянем БД/данные — для консистентного снапшота SQLite надо погасить
    # пишущие процессы. Останавливаем задачу рантайма и пул IIS, копируем,
    # затем поднимаем обратно (в finally, чтобы поднять даже при ошибке копии).
    $pausedTask = $false
    $pausedPool = $false
    if ($IncludeData -or $IncludeDb) {
        Write-Step "Остановка сервисов для консистентного снапшота БД"
        try {
            $t = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
            if ($t -and $t.State -eq 'Running') {
                Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
                $pausedTask = $true
                Write-Ok "задача рантайма остановлена"
            }
        } catch { Write-Warn "не удалось остановить задачу: $($_.Exception.Message)" }
        try {
            Import-Module WebAdministration -ErrorAction SilentlyContinue
            if (Test-Path "IIS:\AppPools\$AppPoolName") {
                if ((Get-WebAppPoolState -Name $AppPoolName).Value -ne 'Stopped') {
                    Stop-WebAppPool -Name $AppPoolName
                    $pausedPool = $true
                    Write-Ok "App Pool '$AppPoolName' остановлен"
                }
            }
        } catch { Write-Warn "не удалось остановить пул: $($_.Exception.Message)" }
        Start-Sleep -Seconds 2
        Write-Step "Код проекта"
    }

    try {
        # Базовые исключения каталогов (соответствуют .gitignore и конвенциям проекта)
        $xd = @(
            ".venv", ".local", ".git", ".codex", ".ruff_cache",
            "__pycache__", "node_modules", "deployments",
            "staticfiles", "static\dist", "clients\*\dist",
            "playwright-report", "test-results", ".playwright-mcp",
            "logs", "caddy_data", "VOB3"
        )
        if (-not $IncludeData)  { $xd += "data" }
        if (-not $IncludeDb)    { $xd += "db" }

        # Исключения ФАЙЛОВ (/XF, не /XD!). sqlite — это файлы, поэтому только здесь.
        $xf = @(
            "*.log", "*.pyc", "server_log.txt", ".env.example.bak"
        )
        if (-not $IncludeDb) {
            $xf += @("*.sqlite3", "*.sqlite3-shm", "*.sqlite3-wal")
        }
        if (-not $IncludeEnv) { $xf += ".env" }
        else                  { Write-Warn "включён .env — в бандле будут СЕКРЕТЫ" }

        # robocopy: /MIR зеркалит, /R:1 /W:1 — минимум ретраев, /NFL /NDL /NP /NJH /NJS — тише лог
        # Коды возврата 0-7 — успех
        $robocopyArgs = @(
            "`"$PortalRoot`""
            "`"$($dirs.Source)`""
            "/MIR", "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH", "/NJS",
            "/XD"
        )
        $robocopyArgs += $xd
        $robocopyArgs += "/XF"
        $robocopyArgs += $xf

        $rc = & robocopy @robocopyArgs
        if ($rc -ge 8) {
            Write-Warn "robocopy вернул код $rc — есть ошибки копирования, проверьте вручную"
        } else {
            Write-Ok "код скопирован в source\"
        }

        $sourceSize = (Get-ChildItem $dirs.Source -Recurse -File -ErrorAction SilentlyContinue |
                       Measure-Object -Property Length -Sum).Sum
        $sourceSizeMb = [math]::Round(($sourceSize / 1MB), 2)
        Write-Host "  Размер source: $sourceSizeMb MB" -ForegroundColor Gray
    }
    finally {
        if ($pausedPool) {
            try { Start-WebAppPool -Name $AppPoolName; Write-Ok "App Pool '$AppPoolName' снова запущен" }
            catch { Write-Warn "НЕ удалось поднять пул '$AppPoolName' — поднимите вручную" }
        }
        if ($pausedTask) {
            try { Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath; Write-Ok "задача рантайма снова запущена" }
            catch { Write-Warn "НЕ удалось поднять задачу — запустите вручную" }
        }
    }
}

# --- Итоговый манифест --------------------------------------------------------
$manifest = [ordered]@{
    bundle_name        = $bundleName
    created_at_utc      = (Get-Date).ToUniversalTime().ToString("o")
    source_host         = $env:COMPUTERNAME
    portal_root         = $PortalRoot
    iis_site            = $SiteName
    iis_apppool         = $AppPoolName
    scheduled_task      = "$TaskPath$TaskName"
    includes            = [ordered]@{
        iis        = -not $SkipIIS
        task       = -not $SkipTask
        firewall   = -not $SkipFirewall
        certs      = -not $SkipCerts
        source     = -not $SkipSource
        data       = [bool]$IncludeData
        db         = [bool]$IncludeDb
        env        = [bool]$IncludeEnv
    }
    target_instructions = "Используйте import_portal.ps1 для восстановления на новом хосте."
}

# Размеры
$sizes = @{}
foreach ($key in @("Iis", "Tasks", "Firewall", "Certs", "Source")) {
    $path = $dirs[$key]
    if (Test-Path $path) {
        $bytes = (Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |
                  Measure-Object -Property Length -Sum).Sum
        $sizes[$key.ToLower()] = [math]::Round(($bytes / 1MB), 2)
    }
}
$manifest["sizes_mb"] = $sizes

Write-Utf8NoBom (Join-Path $bundleRoot "manifest.json") ($manifest | ConvertTo-Json -Depth 6)
Write-Ok "manifest.json"

# --- Архив -------------------------------------------------------------------
Write-Step "Упаковка"
$zipPath = Join-Path $OutputDir "$bundleName.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $bundleRoot -DestinationPath $zipPath -CompressionLevel Optimal
$zipSizeMb = [math]::Round(((Get-Item $zipPath).Length / 1MB), 2)
$msg = "архив: {0} ({1} МБ)" -f $zipPath, $zipSizeMb
Write-Ok $msg

Write-Host ""
Write-Host "=== Экспорт завершён ===" -ForegroundColor Green
Write-Host ""
Write-Host "Следующие шаги:" -ForegroundColor Yellow
Write-Host "  1. Скопируйте архив на новый хост (защищённым каналом)" -ForegroundColor White
Write-Host "  2. Запустите на новом хосте:" -ForegroundColor White
Write-Host "     .\import_portal.ps1 -BundlePath '$zipPath'" -ForegroundColor Gray
Write-Host "  3. Если нужен другой hostname в ALLOWED_HOSTS, добавьте -NewHostname <name>" -ForegroundColor White
Write-Host "  4. Приватные ключи сертификатов и пароль доменного пула перенесите отдельно" -ForegroundColor White
if ($IncludeEnv) {
    Write-Host ""
    Write-Warn ".env включён в бандл — НЕ отправляйте архив по незащищённым каналам"
}
