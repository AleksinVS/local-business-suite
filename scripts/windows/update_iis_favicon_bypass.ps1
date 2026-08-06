# Идемпотентное обновление web.config для устранения гонки Windows SSO/CSRF.
# Скрипт не меняет код Django, базу данных, роли или секреты приложения.

[CmdletBinding()]
param(
    [string]$PortalRoot = "C:\inetpub\portal",
    [string]$SiteName = "",
    [string]$AppPoolName = "",
    [string]$FaviconUrl = "",
    [switch]$CheckOnly,
    [switch]$DryRun,
    [switch]$SkipRecycle,
    [switch]$HandlersOnly
)

$ErrorActionPreference = "Stop"

function Write-Step($message) { Write-Host ""; Write-Host "[$message]" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "  OK  $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "  !   $message" -ForegroundColor Yellow }
function Write-Fail($message) { Write-Host "  X   $message" -ForegroundColor Red }

function Save-WebConfigAtomically {
    param(
        [Parameter(Mandatory = $true)]
        [xml]$Document,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $temporaryPath = "$Destination.tmp-$PID"
    try {
        $settings = New-Object System.Xml.XmlWriterSettings
        $settings.Encoding = New-Object System.Text.UTF8Encoding($false)
        $settings.Indent = $true
        $settings.NewLineChars = "`r`n"
        $settings.NewLineHandling = [System.Xml.NewLineHandling]::Replace
        $writer = [System.Xml.XmlWriter]::Create($temporaryPath, $settings)
        try {
            $Document.Save($writer)
        } finally {
            $writer.Dispose()
        }

        Set-Acl -LiteralPath $temporaryPath -AclObject (Get-Acl -LiteralPath $Destination)
        [xml]$validatedDocument = Get-Content $temporaryPath -Raw
        if ($null -eq $validatedDocument.DocumentElement) {
            throw "Временный web.config не содержит XML document element."
        }
        if (-not (Test-IisFaviconFastCgiBypass -WebConfigPath $temporaryPath)) {
            throw "Временный web.config не прошёл проверку favicon FastCGI bypass."
        }
        [System.IO.File]::Replace($temporaryPath, $Destination, $null)
    } finally {
        if (Test-Path $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Restore-WebConfigAtomically {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupPath,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $rollbackPath = "$Destination.rollback-$PID"
    try {
        Copy-Item -LiteralPath $BackupPath -Destination $rollbackPath
        Set-Acl -LiteralPath $rollbackPath -AclObject (Get-Acl -LiteralPath $BackupPath)
        [xml]$validatedRollback = Get-Content $rollbackPath -Raw
        if ($null -eq $validatedRollback.DocumentElement) {
            throw "Резервная копия web.config не содержит XML document element."
        }
        [System.IO.File]::Replace($rollbackPath, $Destination, $null)
    } finally {
        if (Test-Path $rollbackPath) {
            Remove-Item -LiteralPath $rollbackPath -Force
        }
    }
}

function Invoke-FaviconProbe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    $response = $null
    try {
        $response = Invoke-WebRequest `
            -Uri $Url `
            -UseDefaultCredentials `
            -UseBasicParsing `
            -MaximumRedirection 0 `
            -TimeoutSec 15 `
            -ErrorAction Stop
    } catch {
        if ($null -ne $_.Exception.Response) {
            $response = $_.Exception.Response
        } else {
            throw
        }
    }

    $statusCode = [int]$response.StatusCode
    $contentType = [string]$response.Headers["Content-Type"]
    $hasSetCookie = -not [string]::IsNullOrWhiteSpace([string]$response.Headers["Set-Cookie"])
    $returnsHtmlPage = $statusCode -eq 200 -and $contentType.StartsWith(
        "text/html", [System.StringComparison]::OrdinalIgnoreCase
    )
    $hasExpectedStatus = $statusCode -in @(200, 204, 404)

    Write-Host "  HTTP status: $statusCode"
    Write-Host "  Content-Type: $contentType"
    Write-Host "  Set-Cookie: $(if ($hasSetCookie) { 'present' } else { 'absent' })"

    return [PSCustomObject]@{
        StatusCode = $statusCode
        HasSetCookie = $hasSetCookie
        ReturnsHtmlPage = $returnsHtmlPage
        Safe = ($hasExpectedStatus -and -not $hasSetCookie -and -not $returnsHtmlPage)
    }
}

if ($PortalRoot.EndsWith("\")) {
    $PortalRoot = $PortalRoot.TrimEnd("\")
}
$webConfigPath = Join-Path $PortalRoot "web.config"
$helperPath = Join-Path $PSScriptRoot "iis_web_config.ps1"

Write-Step "Предварительная проверка"
if (-not (Test-Path $helperPath)) {
    Write-Fail "Не найден общий модуль: $helperPath"
    exit 1
}
. $helperPath

if (-not (Test-Path $webConfigPath)) {
    Write-Fail "Не найден web.config: $webConfigPath"
    exit 1
}

try {
    [xml]$webConfig = Get-Content $webConfigPath -Raw
} catch {
    Write-Fail "web.config не является корректным XML: $($_.Exception.Message)"
    exit 1
}

$hasFastCgiBypass = Test-IisFaviconFastCgiBypass -WebConfigPath $webConfigPath
$hasAnonymousBypass = Test-IisFaviconAnonymousBypass -WebConfigPath $webConfigPath
Write-Host "  PortalRoot: $PortalRoot"
Write-Host "  web.config: $webConfigPath"
Write-Host "  FastCGI bypass: $hasFastCgiBypass"
Write-Host "  Anonymous bypass: $hasAnonymousBypass"

if ($CheckOnly) {
    if (-not [string]::IsNullOrWhiteSpace($FaviconUrl)) {
        Write-Step "HTTP-проверка favicon"
        $probe = Invoke-FaviconProbe -Url $FaviconUrl
        if (-not $probe.Safe) {
            Write-Fail "favicon всё ещё возвращает HTML или Set-Cookie."
            exit 2
        }
    }
    if (-not $hasFastCgiBypass -or (-not $HandlersOnly -and -not $hasAnonymousBypass)) {
        Write-Fail "web.config требует обновления."
        exit 2
    }
    Write-Ok "web.config уже защищён от гонки SSO/CSRF."
    exit 0
}

$updateResult = Set-IisFaviconFastCgiBypassXml `
    -WebConfig $webConfig `
    -HandlersOnly:$HandlersOnly

if ($DryRun) {
    Write-Step "Пробный запуск"
    Write-Host "  Изменение требуется: $($updateResult.Changed)"
    Write-Host "  Дубли location для удаления: $($updateResult.RemovedDuplicateLocations)"
    Write-Host "  Резервная копия и запись web.config не выполнялись."
    Write-Host "  Application Pool не перезапускался."
    exit 0
}

if (-not $updateResult.Changed) {
    Write-Ok "web.config уже содержит требуемую конфигурацию; запись не требуется."
    if (-not [string]::IsNullOrWhiteSpace($FaviconUrl)) {
        Write-Step "HTTP-проверка favicon"
        $probe = Invoke-FaviconProbe -Url $FaviconUrl
        if (-not $probe.Safe) {
            Write-Fail "favicon всё ещё возвращает HTML или Set-Cookie."
            exit 3
        }
    }
    exit 0
}

# Повышение прав требуется только для реального изменения и recycle IIS.
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Warn "Для изменения web.config требуются права администратора. Перезапускаю с повышением."
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    foreach ($key in $PSBoundParameters.Keys) {
        $value = $PSBoundParameters[$key]
        if ($value -is [switch]) {
            if ($value.IsPresent) { $arguments += "-$key" }
        } else {
            $arguments += "-$key", "`"$value`""
        }
    }
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $arguments `
        -Verb RunAs `
        -Wait `
        -PassThru
    exit $process.ExitCode
}

Import-Module WebAdministration -ErrorAction Stop
if ([string]::IsNullOrWhiteSpace($SiteName)) {
    $normalizedRoot = [System.IO.Path]::GetFullPath($PortalRoot).TrimEnd("\")
    $matchingSites = @(
        Get-Website | Where-Object {
            -not [string]::IsNullOrWhiteSpace([string]$_.physicalPath) -and
            [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables([string]$_.physicalPath)).TrimEnd("\").Equals(
                $normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase
            )
        }
    )
    if ($matchingSites.Count -ne 1) {
        Write-Fail "Не удалось однозначно определить IIS SiteName для $PortalRoot. Передайте -SiteName явно."
        exit 1
    }
    $SiteName = [string]$matchingSites[0].Name
}

$site = Get-Website -Name $SiteName -ErrorAction Stop
if ([string]::IsNullOrWhiteSpace($AppPoolName)) {
    $AppPoolName = [string]$site.applicationPool
}
if ([string]::IsNullOrWhiteSpace($AppPoolName)) {
    Write-Fail "Не удалось определить Application Pool. Передайте -AppPoolName явно."
    exit 1
}
Write-Host "  SiteName: $SiteName"
Write-Host "  AppPoolName: $AppPoolName"

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$backupPath = "$webConfigPath.backup-$timestamp"
$configApplied = $false

Write-Step "Резервная копия и применение"
try {
    Copy-Item -LiteralPath $webConfigPath -Destination $backupPath
    Set-Acl -LiteralPath $backupPath -AclObject (Get-Acl -LiteralPath $webConfigPath)
    Write-Ok "Резервная копия: $backupPath"

    Save-WebConfigAtomically -Document $webConfig -Destination $webConfigPath
    $configApplied = $true

    if (-not (Test-IisFaviconFastCgiBypass -WebConfigPath $webConfigPath)) {
        throw "Записанный web.config не содержит favicon FastCGI bypass."
    }
    if (-not $HandlersOnly -and -not (Test-IisFaviconAnonymousBypass -WebConfigPath $webConfigPath)) {
        throw "Записанный web.config не содержит ожидаемые authentication overrides."
    }

    $appcmd = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"
    & $appcmd list config "$SiteName/favicon.ico" /section:system.webServer/handlers | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "IIS отклонил конфигурацию handlers для favicon.ico (appcmd exit $LASTEXITCODE)."
    }

    if (-not $SkipRecycle) {
        Restart-WebAppPool -Name $AppPoolName
        Write-Ok "Application Pool перезапущен: $AppPoolName"
    } else {
        Write-Warn "Recycle Application Pool пропущен по параметру -SkipRecycle."
    }
} catch {
    Write-Fail "Ошибка применения: $($_.Exception.Message)"
    if ($configApplied -and (Test-Path $backupPath)) {
        try {
            Restore-WebConfigAtomically -BackupPath $backupPath -Destination $webConfigPath
            if (-not $SkipRecycle) {
                Restart-WebAppPool -Name $AppPoolName
            }
            Write-Warn "Исходный web.config автоматически восстановлен из $backupPath"
        } catch {
            Write-Fail "Автоматический откат не удался: $($_.Exception.Message)"
            Write-Fail "Восстановите вручную резервную копию: $backupPath"
        }
    }
    if (-not $HandlersOnly) {
        Write-Warn "Если IIS блокирует authentication overrides, проверьте ошибку и повторите с -HandlersOnly."
    }
    exit 1
}

Write-Ok "favicon.ico исключён из FastCGI; web.config применён идемпотентно."
if (-not [string]::IsNullOrWhiteSpace($FaviconUrl)) {
    Write-Step "HTTP-проверка favicon"
    $probe = Invoke-FaviconProbe -Url $FaviconUrl
    if (-not $probe.Safe) {
        Write-Fail "Конфигурация записана, но favicon всё ещё возвращает HTML или Set-Cookie."
        Write-Warn "Проверьте handler inheritance и IIS logs. Резервная копия: $backupPath"
        exit 3
    }
    Write-Ok "favicon не возвращает HTML главной страницы и не устанавливает cookie."
}

Write-Step "Готово"
Write-Host "  web.config: $webConfigPath"
Write-Host "  backup: $backupPath"
Write-Host "  rollback: Copy-Item -LiteralPath `"$backupPath`" -Destination `"$webConfigPath`" -Force"
