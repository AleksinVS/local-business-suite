# Import Portal Configuration from Migration Bundle
# Восстанавливает Portal из бандла, снятого export_portal.ps1.
#
# Назначение: штатная миграция portal на новый Windows-хост
# (например, Windows 10 Pro после Windows Server 2022).
#
# Использование:
#   .\import_portal.ps1 -BundlePath C:\temp\portal-export-20260702-153045.zip
#   .\import_portal.ps1 -BundlePath <zip> -NewHostname stc-web2
#   .\import_portal.ps1 -BundlePath <zip> -SkipIIS -SkipTask   # только код и venv
#   .\import_portal.ps1 -BundlePath <zip> -DryRun             # показать, что будет сделано
#
# Что делает:
#   1. Распаковывает бандл
#   2. Включает IIS-фичи (DISM на клиентских Windows)
#   3. Открывает порты 80/443 в брандмауэре
#   4. Копирует код в C:\inetpub\portal
#   5. Восстанавливает .env с подстановкой hostname (если задан -NewHostname)
#   6. Пересоздаёт .venv из requirements.txt
#   7. Создаёт App Pool и сайт в IIS
#   8. Регистрирует wfastcgi handler
#   9. Импортирует Scheduled Task и запускает runtime
#  10. Проверяет /health на runtime и корень на IIS

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BundlePath,
    [string]$PortalRoot = "C:\inetpub\portal",
    [string]$SiteName = "portal",
    [string]$AppPoolName = "portal",
    [string]$TaskName = "Portal Agent Runtime",
    [string]$TaskPath = "\Portal\",
    [string]$PythonExe = "$env:ProgramFiles\Python311\python.exe",
    [string]$NewHostname,
    [int]$RuntimePort = 8090,
    [switch]$SkipIIS,
    [switch]$SkipCode,
    [switch]$SkipVenv,
    [switch]$SkipTask,
    [switch]$SkipFirewall,
    [switch]$NoStart,
    [switch]$DryRun,
    [switch]$Force
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

Write-Host "=== Import Portal Configuration ===" -ForegroundColor Cyan
Write-Host ""

if ($PortalRoot.EndsWith("\")) { $PortalRoot = $PortalRoot.TrimEnd("\") }
if ($TaskPath -and -not $TaskPath.StartsWith("\")) { $TaskPath = "\$TaskPath" }
if ($TaskPath -and -not $TaskPath.EndsWith("\"))    { $TaskPath = "$TaskPath\" }

# --- Утилиты -----------------------------------------------------------------
function Write-Step($name) { Write-Host ""; Write-Host "[$name]" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Skip($msg)  { Write-Host "  - $msg" -ForegroundColor Gray }
function Run-Or-Dry([scriptblock]$action, [string]$what) {
    if ($DryRun) { Write-Host "  [DRY-RUN] $what" -ForegroundColor Magenta }
    else         { & $action }
}

# --- Pre-flight: проверка бандла ---------------------------------------------
Write-Step "Проверка бандла"

if (-not (Test-Path $BundlePath)) {
    Write-Host "ОШИБКА: Бандл не найден: $BundlePath" -ForegroundColor Red
    exit 1
}
Write-Ok "BundlePath: $BundlePath"
$bundleSize = [math]::Round((Get-Item $BundlePath).Length / 1MB, 2)
Write-Host "  Размер: $bundleSize MB" -ForegroundColor Gray

$stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
$workDir = Join-Path $env:TEMP "portal-import-$stamp"
Run-Or-Dry { New-Item -ItemType Directory -Path $workDir -Force | Out-Null } "создать $workDir"
Write-Ok "Распаковка в: $workDir"
if (-not $DryRun) {
    Expand-Archive -Path $BundlePath -DestinationPath $workDir -Force
}

# manifest.json — должен быть в корне бандла или внутри единственной подпапки
$manifestPath = Join-Path $workDir "manifest.json"
if (-not (Test-Path $manifestPath)) {
    $candidates = Get-ChildItem $workDir -Directory | Select-Object -First 1
    if ($candidates -and (Test-Path (Join-Path $candidates.FullName "manifest.json"))) {
        $workDir = $candidates.FullName
        $manifestPath = Join-Path $workDir "manifest.json"
    }
}
if (-not (Test-Path $manifestPath)) {
    Write-Host "ОШИБКА: manifest.json не найден в бандле" -ForegroundColor Red
    exit 1
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$bundleNameSrc = $manifest.bundle_name
$srcHost = $manifest.source_host
Write-Ok "manifest.json: bundle=$bundleNameSrc, source_host=$srcHost"

# Имена из manifest, если не переданы явно
if (-not $PSBoundParameters.ContainsKey('SiteName') -and $manifest.iis_site)        { $SiteName = $manifest.iis_site }
if (-not $PSBoundParameters.ContainsKey('AppPoolName') -and $manifest.iis_apppool) { $AppPoolName = $manifest.iis_apppool }
if (-not $PSBoundParameters.ContainsKey('TaskName') -and $manifest.scheduled_task) {
    $tn = $manifest.scheduled_task -replace ".*\\", ""
    if ($tn) { $TaskName = $tn }
}
if (-not $PSBoundParameters.ContainsKey('TaskPath') -and $manifest.scheduled_task) {
    $tp = $manifest.scheduled_task
    if ($tp -match "^(\\[^\\]+\\?)") { $TaskPath = $Matches[1] }
}

Write-Host "  Целевой сайт: $SiteName" -ForegroundColor Gray
Write-Host "  Целевой пул:  $AppPoolName" -ForegroundColor Gray
Write-Host "  Целевая задача: $TaskPath$TaskName" -ForegroundColor Gray
Write-Host "  PortalRoot:   $PortalRoot" -ForegroundColor Gray

if (-not $NewHostname) {
    $currentHostname = $env:COMPUTERNAME
    if ($manifest.source_host -and $manifest.source_host -ne $currentHostname) {
        Write-Warn "Исходный хост: $($manifest.source_host), текущий: $currentHostname"
        Write-Warn "Рекомендую указать -NewHostname $currentHostname для корректных ALLOWED_HOSTS"
    }
}

# --- Включение IIS-фич (на Windows 10 Pro это DISM, на Server — Install-WindowsFeature) -
Write-Step "IIS-фичи"

if ($SkipIIS) {
    Write-Skip "пропущено (SkipIIS)"
} else {
    $hasInstallWindowsFeature = Get-Command Install-WindowsFeature -ErrorAction SilentlyContinue
    if ($hasInstallWindowsFeature) {
        # Windows Server
        $features = @("Web-Server", "Web-CGI", "Web-Static-Content")
        foreach ($f in $features) {
            $state = Get-WindowsFeature $f -ErrorAction SilentlyContinue
            if ($state -and -not $state.Installed) {
                Run-Or-Dry { Install-WindowsFeature -Name $f | Out-Null } "Install-WindowsFeature $f"
                Write-Ok "Install-WindowsFeature $f"
            } else {
                Write-Skip "$f уже установлен"
            }
        }
    } else {
        # Windows 10 Pro / клиентские редакции
        $iisCgi = Get-WindowsOptionalFeature -Online -FeatureName "IIS-CGI" -ErrorAction SilentlyContinue
        if ($iisCgi -and $iisCgi.State -ne "Enabled") {
            Run-Or-Dry { Enable-WindowsOptionalFeature -Online -FeatureName "IIS-WebServer", "IIS-CGI" -NoRestart -ErrorAction Stop | Out-Null } "Enable-WindowsOptionalFeature IIS-CGI"
            Write-Ok "Включены IIS-WebServer, IIS-CGI"
        } else {
            Write-Skip "IIS-CGI уже включён"
        }
    }

    $appcmd = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"
    if (-not (Test-Path $appcmd) -and -not $DryRun) {
        Write-Host "ОШИБКА: appcmd.exe не найден после установки IIS" -ForegroundColor Red
        exit 1
    }
    Write-Ok "IIS готов"
}

# --- Firewall ----------------------------------------------------------------
Write-Step "Firewall"

if ($SkipFirewall) {
    Write-Skip "пропущено (SkipFirewall)"
} else {
    $rules = @(
        @{ Name = "Portal HTTP";  Port = 80  }
        @{ Name = "Portal HTTPS"; Port = 443 }
    )
    foreach ($r in $rules) {
        $existing = Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Skip "$($r.Name) уже есть"
            continue
        }
        Run-Or-Dry {
            New-NetFirewallRule -DisplayName $r.Name -Direction Inbound `
                -Protocol TCP -LocalPort $r.Port -Action Allow -Profile Any | Out-Null
        } "New-NetFirewallRule $($r.Name) TCP $($r.Port)"
        Write-Ok "$($r.Name) (TCP $($r.Port))"
    }
}

# --- Копия кода --------------------------------------------------------------
Write-Step "Код проекта"

$sourceDir = Join-Path $workDir "source"
if (-not (Test-Path $sourceDir)) {
    Write-Warn "source/ не найден в бандле — копирование кода пропущено"
} elseif ($SkipCode) {
    Write-Skip "пропущено (SkipCode)"
} else {
    if (Test-Path $PortalRoot) {
        if (-not $Force) {
            Write-Host "ОШИБКА: $PortalRoot уже существует. Используйте -Force для перезаписи или -SkipCode." -ForegroundColor Red
            exit 1
        }
        Write-Warn "PortalRoot существует — будет выполнено зеркальное копирование (Force)"
    } else {
        Run-Or-Dry { New-Item -ItemType Directory -Path $PortalRoot -Force | Out-Null } "создать $PortalRoot"
    }
    if (-not $DryRun) {
        # robocopy /MIR перезапишет содержимое PortalRoot содержимым source
        $rc = & robocopy "`"$sourceDir`"" "`"$PortalRoot`"" /MIR /R:1 /W:1 /NFL /NDL /NP /NJH /NJS
        if ($rc -ge 8) {
            Write-Warn "robocopy вернул код $rc — есть ошибки"
        } else {
            Write-Ok "код скопирован"
        }
    } else {
        Write-Host "  [DRY-RUN] robocopy source -> $PortalRoot /MIR" -ForegroundColor Magenta
    }

    # web.config — отдельно кладём из бандла/iis, если есть
    $webCfgInBundle = Join-Path $workDir "iis\web.config"
    if (Test-Path $webCfgInBundle) {
        if (-not $DryRun) {
            Copy-Item -Path $webCfgInBundle -Destination (Join-Path $PortalRoot "web.config") -Force
        }
        Write-Ok "web.config из бандла"
    }
}

# --- .env --------------------------------------------------------------------
Write-Step ".env"

if ($SkipCode) {
    Write-Skip "пропущено (SkipCode)"
} else {
    $envPath = Join-Path $PortalRoot ".env"
    $envExamplePath = Join-Path $PortalRoot ".env.example"
    $envInBundle = Join-Path $sourceDir ".env"

    if (Test-Path $envInBundle) {
        Run-Or-Dry { Copy-Item -Path $envInBundle -Destination $envPath -Force } "скопировать .env из бандла"
        Write-Ok ".env из бандла"
    } elseif (Test-Path $envExamplePath) {
        Run-Or-Dry { Copy-Item -Path $envExamplePath -Destination $envPath -Force } "скопировать .env из .env.example"
        Write-Warn ".env создан из .env.example — заполните секреты вручную"
    } else {
        Write-Warn ".env не найден — приложение может не стартовать без секретов"
    }

    # Подстановка hostname
    if ($NewHostname -and (Test-Path $envPath) -and -not $DryRun) {
        $envContent = Get-Content $envPath -Raw
        $allowedOld = ([regex]::Match($envContent, '(?m)^DJANGO_ALLOWED_HOSTS\s*=\s*(.+)$')).Groups[1].Value
        if ($allowedOld) {
            $allowedOldClean = $allowedOld.Trim().Trim('"').Trim("'")
            $allowedNew = "$allowedOldClean,$NewHostname" -split ',' | Where-Object { $_ } | Select-Object -Unique
            $newLine = "DJANGO_ALLOWED_HOSTS=`"$($allowedNew -join ',')`""
            $envContent = $envContent -replace '(?m)^DJANGO_ALLOWED_HOSTS\s*=.*$', $newLine
            Write-Ok "DJANGO_ALLOWED_HOSTS обновлён: $($allowedNew -join ',')"
        }
        $gwOld = ([regex]::Match($envContent, '(?m)^DJANGO_AI_GATEWAY_URL\s*=\s*(.+)$')).Groups[1].Value
        if ($gwOld) {
            $newGw = "http://$NewHostname/ai/gateway"
            $envContent = $envContent -replace '(?m)^DJANGO_AI_GATEWAY_URL\s*=.*$', "DJANGO_AI_GATEWAY_URL=`"$newGw`""
            Write-Ok "DJANGO_AI_GATEWAY_URL = $newGw"
        }
        Set-Content -Path $envPath -Value $envContent -Encoding UTF8 -NoNewline
    }
}

# --- venv --------------------------------------------------------------------
Write-Step "Python venv"

if ($SkipCode) {
    Write-Skip "пропущено (SkipCode)"
} elseif ($SkipVenv) {
    Write-Skip "пропущено (SkipVenv)"
} else {
    if (-not (Test-Path $PythonExe) -and -not $DryRun) {
        Write-Host "ОШИБКА: Python не найден: $PythonExe" -ForegroundColor Red
        Write-Host "Установите Python 3.11 и передайте путь через -PythonExe" -ForegroundColor Yellow
        exit 1
    }
    Write-Ok "Python: $PythonExe"

    $venvDir = Join-Path $PortalRoot ".venv"
    if (Test-Path $venvDir) {
        if ($Force) {
            Run-Or-Dry { Remove-Item -Path $venvDir -Recurse -Force } "удалить существующий venv"
        } else {
            Write-Skip ".venv уже существует (используйте -Force для пересоздания)"
        }
    }

    if (-not (Test-Path $venvDir)) {
        Run-Or-Dry {
            & $PythonExe -m venv $venvDir
            & (Join-Path $venvDir "Scripts\python.exe") -m pip install --upgrade pip | Out-Null
            $req = Join-Path $PortalRoot "requirements.txt"
            if (Test-Path $req) {
                & (Join-Path $venvDir "Scripts\python.exe") -m pip install -r $req | Out-Null
            }
        } "создать venv и установить зависимости"
        Write-Ok "venv создан и зависимости установлены"
    }

    # wfastcgi — критичный для IIS пакет
    $wfastcgiExe = Join-Path $venvDir "Scripts\wfastcgi-enable.exe"
    if (Test-Path $wfastcgiExe) {
        Write-Ok "wfastcgi доступен: $wfastcgiExe"
    } else {
        Write-Warn "wfastcgi не установлен в venv (он нужен для IIS)"
    }
}

# --- IIS: App Pool -----------------------------------------------------------
Write-Step "IIS: AppPool"

if ($SkipIIS) {
    Write-Skip "пропущено (SkipIIS)"
} else {
    Import-Module WebAdministration -ErrorAction Stop

    if (Test-Path "IIS:\AppPools\$AppPoolName") {
        Run-Or-Dry {
            if ((Get-WebAppPoolState -Name $AppPoolName).Value -ne "Stopped") {
                Stop-WebAppPool -Name $AppPoolName -ErrorAction SilentlyContinue
            }
            Remove-WebAppPool -Name $AppPoolName
        } "удалить существующий пул $AppPoolName"
        Write-Ok "удалён существующий пул $AppPoolName"
    }

    Run-Or-Dry {
        New-WebAppPool -Name $AppPoolName -Force | Out-Null
        Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name managedRuntimeVersion -Value ""
        Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name startMode -Value "AlwaysRunning"
        Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name processModel.identityType -Value "ApplicationPoolIdentity"
    } "создать AppPool $AppPoolName"
    Write-Ok "AppPool $AppPoolName создан (No Managed Code, AlwaysRunning)"
}

# --- IIS: Site + wfastcgi ----------------------------------------------------
Write-Step "IIS: Site + wfastcgi"

if ($SkipIIS) {
    Write-Skip "пропущено (SkipIIS)"
} else {
    if (Test-Path "IIS:\Sites\$SiteName") {
        Run-Or-Dry {
            Stop-Website -Name $SiteName -ErrorAction SilentlyContinue
            Remove-Website -Name $SiteName
        } "удалить существующий сайт $SiteName"
        Write-Ok "удалён существующий сайт $SiteName"
    }

    Run-Or-Dry {
        # Привязка только к HTTP:80 — HTTPS-сертификат добавляется оператором вручную после импорта.
        New-Website -Name $SiteName -Port 80 -PhysicalPath $PortalRoot -ApplicationPool $AppPoolName | Out-Null
    } "New-Website $SiteName -> $PortalRoot :80"
    Write-Ok "сайт $SiteName создан"

    # wfastcgi регистрация
    $wfastcgiExe = Join-Path $PortalRoot ".venv\Scripts\wfastcgi-enable.exe"
    if (Test-Path $wfastcgiExe) {
        Run-Or-Dry {
            $proc = Start-Process -FilePath $wfastcgiExe -NoNewWindow -Wait -PassThru -RedirectStandardOutput "NUL" -RedirectStandardError "NUL"
        } "wfastcgi-enable"
        Write-Ok "wfastcgi зарегистрирован"
    } else {
        Write-Warn "wfastcgi-enable.exe не найден — handler придётся настроить вручную"
    }
}

# --- Scheduled Task ----------------------------------------------------------
Write-Step "Scheduled Task"

if ($SkipTask) {
    Write-Skip "пропущено (SkipTask)"
} else {
    $taskXmlInBundle = Get-ChildItem (Join-Path $workDir "tasks") -Filter "*.xml" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $taskXmlInBundle) {
        Write-Warn "XML задачи не найден в бандле (tasks/)"
    } else {
        $existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
        if ($existing) {
            Run-Or-Dry {
                Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
            } "удалить существующую задачу $TaskPath$TaskName"
            Write-Ok "удалена существующая задача"
        }

        Run-Or-Dry {
            Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath `
                -Xml (Get-Content $taskXmlInBundle.FullName -Raw) `
                -User "SYSTEM" -RunLevel Highest -Force | Out-Null
        } "Register-ScheduledTask"
        Write-Ok "задача $TaskPath$TaskName зарегистрирована"
    }
}

# --- Запуск runtime + проверки -----------------------------------------------
Write-Step "Запуск и проверки"

if ($NoStart) {
    Write-Skip "запуск пропущен (NoStart)"
} else {
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
    if ($task) {
        Run-Or-Dry { Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath } "Start-ScheduledTask"
        Write-Ok "задача запущена"
        Write-Host "  Ждём ~5 секунд..." -ForegroundColor Gray
        if (-not $DryRun) { Start-Sleep -Seconds 5 }

        $healthUrl = "http://127.0.0.1:$RuntimePort/health"
        try {
            $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5 -ErrorAction Stop
            Write-Ok "runtime /health: $($resp.status)"
        } catch {
            $errMsg = $_.Exception.Message
            Write-Warn "runtime /health не отвечает: $errMsg"
            Write-Host "    Проверьте логи в .local\agent_runtime*.log" -ForegroundColor Gray
        }
    } else {
        Write-Warn "задача не зарегистрирована, runtime не запущен"
    }
}

# IIS health (HEAD /)
try {
    $req = [System.Net.HttpWebRequest]::Create("http://localhost/")
    $req.Method = "GET"
    $req.Timeout = 5000
    $req.AllowAutoRedirect = $false
    $resp = $req.GetResponse()
    Write-Ok "IIS localhost: HTTP $($resp.StatusCode)"
    $resp.Close()
} catch [System.Net.WebException] {
    $code = $_.Exception.Response.StatusCode.value__
    Write-Ok "IIS localhost: HTTP $code"
} catch {
    $errMsg = $_.Exception.Message
    Write-Warn "IIS localhost не отвечает: $errMsg"
}

Write-Host ""
Write-Host "=== Импорт завершён ===" -ForegroundColor Green
Write-Host ""
Write-Host "Дальнейшие шаги:" -ForegroundColor Yellow
if (-not $NewHostname) {
    Write-Host "  1. Проверьте DJANGO_ALLOWED_HOSTS в .env — там должно быть имя этого хоста" -ForegroundColor White
    Write-Host "  2. Проверьте DJANGO_AI_GATEWAY_URL — оно должно использовать имя из ALLOWED_HOSTS" -ForegroundColor White
}
Write-Host "  3. Если используется HTTPS — импортируйте сертификаты и добавьте привязку 443 в IIS" -ForegroundColor White
Write-Host "  4. Перезагрузите хост и убедитесь, что Scheduled Task поднимает runtime автоматически" -ForegroundColor White
Write-Host "  5. Откройте портал в браузере, проверьте чат ИИ с реальным запросом данных" -ForegroundColor White