# Configure wfastcgi for Django on IIS
# Настройка wfastcgi для запуска Django через IIS на целевом хосте.
#
# Использование:
#   .\setup_wfastcgi.ps1
#   .\setup_wfastcgi.ps1 -PortalRoot "C:\inetpub\portal"
#   .\setup_wfastcgi.ps1 -CheckOnly
#
# Что делает:
#   1. Проверяет/устанавливает FastCGI Module для IIS
#   2. Проверяет наличие .venv и python.exe
#   3. Регистрирует wfastcgi через wfastcgi-enable.exe
#   4. Добавляет handler в web.config или IIS
#   5. Перезапускает AppPool
#
# Требования:
#   - IIS установлен
#   - Python .venv существует в PortalRoot
#   - Права администратора

[CmdletBinding()]
param(
    [string]$PortalRoot = "C:\inetpub\portal",
    [string]$SiteName = "Default Web Site",
    [string]$AppPoolName = "DefaultAppPool",
    [switch]$CheckOnly,
    [switch]$SkipFastCgiInstall
)

$ErrorActionPreference = "Stop"

# --- Самоподъём до администратора --------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Admin rights required. Relaunching elevated..." -ForegroundColor Yellow
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

# --- Утилиты -----------------------------------------------------------------
function Write-Step($name) { Write-Host ""; Write-Host "[$name]" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  !   $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "  X   $msg" -ForegroundColor Red }

Write-Host "=== Configure wfastcgi for Django ===" -ForegroundColor Cyan
Write-Host ""

# --- Init -------------------------------------------------------------------
Import-Module WebAdministration -ErrorAction Stop
$appcmd = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"

# Normalize paths
if ($PortalRoot.EndsWith("\")) { $PortalRoot = $PortalRoot.TrimEnd("\") }

Write-Step "Parameters"
Write-Host "  PortalRoot:  $PortalRoot" -ForegroundColor Gray
Write-Host "  SiteName:    $SiteName" -ForegroundColor Gray
Write-Host "  AppPoolName: $AppPoolName" -ForegroundColor Gray

# --- Pre-flight: проверка компонентов ---------------------------------------
Write-Step "Check components"

# Check IIS
$iiSrv = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"
if (-not (Test-Path $iiSrv)) {
    Write-Fail "IIS not installed (appcmd.exe not found)"
    exit 1
}
Write-Ok "IIS installed"

# Check PortalRoot
if (-not (Test-Path $PortalRoot)) {
    Write-Fail "PortalRoot not found: $PortalRoot"
    exit 1
}
Write-Ok "PortalRoot exists"

# Check manage.py
if (-not (Test-Path (Join-Path $PortalRoot "manage.py"))) {
    Write-Warn "manage.py not found - may not be a Django project"
}

# --- Check only mode ---------------------------------------------------------
if ($CheckOnly) {
    Write-Step "Current wfastcgi status"

    # Check FastCGI Module
    $fcgiInstalled = $false
    try {
        $isServer = $null -ne (Get-Command Install-WindowsFeature -ErrorAction SilentlyContinue)
        if ($isServer) {
            $fcgi = Get-WindowsFeature -Name Web-CGI -ErrorAction SilentlyContinue
            if ($fcgi -and $fcgi.Installed) { $fcgiInstalled = $true }
        } else {
            $fcgi = Get-WindowsOptionalFeature -Online -FeatureName IIS-CGI -ErrorAction SilentlyContinue
            if ($fcgi -and $fcgi.State -eq "Enabled") { $fcgiInstalled = $true }
        }
    } catch { }

    Write-Host "  FastCGI Module: $($fcgiInstalled -or $SkipFastCgiInstall)" -ForegroundColor $(if ($fcgiInstalled) { "Green" } else { "Yellow" })

    # Check .venv
    $venvDir = Join-Path $PortalRoot ".venv"
    $pythonExe = Join-Path $venvDir "Scripts\python.exe"
    $wfastcgiPy = Join-Path $venvDir "Lib\site-packages\wfastcgi.py"

    Write-Host "  .venv:          $(Test-Path $venvDir)" -ForegroundColor $(if (Test-Path $venvDir) { "Green" } else { "Red" })
    Write-Host "  python.exe:    $(Test-Path $pythonExe)" -ForegroundColor $(if (Test-Path $pythonExe) { "Green" } else { "Red" })
    Write-Host "  wfastcgi.py:   $(Test-Path $wfastcgiPy)" -ForegroundColor $(if (Test-Path $wfastcgiPy) { "Green" } else { "Red" })

    # Check registered wfastcgi
    try {
        $registered = & $appcmd list config -section:system.webServer/fastCgi 2>&1 | Select-String "python.exe" -Quiet
        Write-Host "  wfastcgi registered: $registered" -ForegroundColor $(if ($registered) { "Green" } else { "Yellow" })
    } catch { Write-Host "  wfastcgi registered: false" -ForegroundColor Yellow }

    # Check handler
    try {
        $handler = Get-WebConfiguration -Filter "/system.webServer/handlers" -PSPath "IIS:\Sites\$SiteName" -ErrorAction SilentlyContinue
        if ($handler) {
            $pythonHandler = $handler.Collection | Where-Object { $_.Name -like "*Python*" -or $_.scriptProcessor -like "*python.exe*" }
            Write-Host "  Python handler:  $(($pythonHandler -ne $null).Count -gt 0)" -ForegroundColor $(if ($pythonHandler) { "Green" } else { "Yellow" })
        }
    } catch { Write-Host "  Python handler:  error checking" -ForegroundColor Yellow }

    exit 0
}

# --- Step 1: Install FastCGI Module ----------------------------------------
Write-Step "Install FastCGI Module"

if ($SkipFastCgiInstall) {
    Write-Skip "skipped (SkipFastCgiInstall)"
} else {
    try {
        # Detect OS type (Server vs Client)
        $isServer = $null -ne (Get-Command Install-WindowsFeature -ErrorAction SilentlyContinue)

        if ($isServer) {
            # Windows Server
            $fcgi = Get-WindowsFeature -Name Web-CGI -ErrorAction Stop
            if ($fcgi.Installed) {
                Write-Ok "FastCGI Module already installed"
            } else {
                Write-Host "  Installing FastCGI Module (Server)..." -ForegroundColor Yellow
                Install-WindowsFeature -Name Web-CGI -IncludeManagementTools | Out-Null
                Write-Ok "FastCGI Module installed"
            }
        } else {
            # Windows 10/11 Client
            $fcgi = Get-WindowsOptionalFeature -Online -FeatureName IIS-CGI -ErrorAction Stop
            if ($fcgi.State -eq "Enabled") {
                Write-Ok "FastCGI Module already installed"
            } else {
                Write-Host "  Installing FastCGI Module (Client)..." -ForegroundColor Yellow
                Enable-WindowsOptionalFeature -Online -FeatureName IIS-CGI -NoRestart -ErrorAction Stop | Out-Null
                Write-Ok "FastCGI Module installed"
            }
        }
    } catch {
        Write-Fail "Failed to install FastCGI Module: $($_.Exception.Message)"
        Write-Host "Install manually:" -ForegroundColor Yellow
        if ($isServer) {
            Write-Host "  Install-WindowsFeature -Name Web-CGI -IncludeManagementTools" -ForegroundColor Gray
        } else {
            Write-Host "  Enable-WindowsOptionalFeature -Online -FeatureName IIS-CGI -NoRestart" -ForegroundColor Gray
        }
        exit 1
    }
}

# --- Step 2: Check .venv ---------------------------------------------------
Write-Step "Check Python .venv"

$venvDir = Join-Path $PortalRoot ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"
$wfastcgiPy = Join-Path $venvDir "Lib\site-packages\wfastcgi.py"
$wfastcgiEnable = Join-Path $venvDir "Scripts\wfastcgi-enable.exe"

if (-not (Test-Path $pythonExe)) {
    Write-Fail "Python not found: $pythonExe"
    Write-Host "Create .venv first: python -m venv $venvDir" -ForegroundColor Yellow
    exit 1
}
Write-Ok "Python found: $pythonExe"

if (-not (Test-Path $wfastcgiPy)) {
    Write-Warn "wfastcgi.py not found - install wfastcgi"
    Write-Host "  Run: & '$pythonExe' -m pip install wfastcgi" -ForegroundColor Gray
}

if (-not (Test-Path $wfastcgiEnable)) {
    Write-Warn "wfastcgi-enable.exe not found - may need to register manually"
}

# --- Step 3: Register wfastcgi ---------------------------------------------
Write-Step "Register wfastcgi"

if (Test-Path $wfastcgiEnable) {
    Write-Host "  Running wfastcgi-enable.exe..." -ForegroundColor Gray
    try {
        $proc = Start-Process -FilePath $wfastcgiEnable -NoNewWindow -Wait -PassThru -RedirectStandardOutput "NUL" -RedirectStandardError "NUL"
        if ($proc.ExitCode -eq 0) {
            Write-Ok "wfastcgi registered successfully"
        } else {
            Write-Warn "wfastcgi-enable.exe exited with code $($proc.ExitCode)"
        }
    } catch {
        Write-Warn "Failed to run wfastcgi-enable.exe: $($_.Exception.Message)"
    }
} else {
    # Manual registration via appcmd
    Write-Host "  Registering wfastcgi via appcmd..." -ForegroundColor Gray
    try {
        $scriptProcessor = "$pythonExe|$wfastcgiPy"
        & $appcmd set config -section:system.webServer/fastCgi /+"`"fullPath=`"$pythonExe`""` /argumentNames:`"-c`" | Out-Null
        Write-Ok "wfastcgi registered via appcmd"
    } catch {
        Write-Warn "Manual registration may be required"
    }
}

# --- Step 4: Configure handler ---------------------------------------------
Write-Step "Configure Python handler"

# Build scriptProcessor path
$scriptProcessor = "$pythonExe|$wfastcgiPy"
$scriptProcessor = $scriptProcessor.Replace('\', '/')

# Check if handler already exists
$existingHandler = Get-WebConfiguration -Filter "/system.webServer/handlers" -PSPath "IIS:\Sites\$SiteName" -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Collection | Where-Object { $_.Name -eq "Python FastCGI" -or $_.scriptProcessor -like "*python.exe*" }

if ($existingHandler) {
    Write-Warn "Python handler already exists - will update"
}

# Add or update handler (skip if already configured)
if ($existingHandler) {
    Write-Ok "Python handler already configured - skipping"
} else {
    try {
        # Use appcmd to add handler (non-interactive)
        $scriptProcessorEscaped = $scriptProcessor.Replace('\', '/')
        $addCmd = "/add name=`"Python FastCGI`" path=`"*`" verb=`"*`" modules=`"FastCgiModule`" scriptProcessor=`"$scriptProcessorEscaped`" resourceType=`"Unspecified`" requireAccess=`"Script`" allowPathInfo=`"true`" responseBufferLimit=`"4194304`""
        & $appcmd set config "$SiteName/" -section:system.webServer/handlers $addCmd | Out-Null
        Write-Ok "Python handler configured: Python FastCGI"
    } catch {
        Write-Fail "Failed to configure handler: $($_.Exception.Message)"
        Write-Host "  You may need to add handler manually in web.config or IIS Manager" -ForegroundColor Yellow
        exit 1
    }
}

# --- Step 5: Configure AppPool (No Managed Code) -------------------------
Write-Step "Configure AppPool"

try {
    # Set managedRuntimeVersion to empty (No Managed Code)
    Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name "managedRuntimeVersion" -Value "" -ErrorAction Stop
    Write-Ok "AppPool set to No Managed Code"

    # Set startMode to AlwaysRunning
    Set-ItemProperty "IIS:\AppPools\$AppPoolName" -Name "startMode" -Value "AlwaysRunning" -ErrorAction SilentlyContinue
    Write-Ok "AppPool startMode: AlwaysRunning"
} catch {
    Write-Warn "Failed to configure AppPool: $($_.Exception.Message)"
}

# --- Step 6: Restart AppPool -----------------------------------------------
Write-Step "Restart AppPool"

try {
    Restart-WebAppPool -Name $AppPoolName
    Write-Ok "AppPool restarted: $AppPoolName"
} catch {
    Write-Warn "Failed to restart AppPool: $($_.Exception.Message)"
    Write-Host "  Restart manually: Restart-WebAppPool -Name '$AppPoolName'" -ForegroundColor Gray
}

# --- Step 7: Verify --------------------------------------------------------
Write-Step "Verification"

Write-Host "  Testing wfastcgi response..." -ForegroundColor Gray
try {
    # Test if wfastcgi responds (simple request)
    $response = Invoke-WebRequest -Uri "http://localhost/" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    if ($response.StatusCode -eq 200) {
        Write-Ok "Site responds with HTTP $($response.StatusCode)"
    }
} catch {
    Write-Warn "Site test failed: $($_.Exception.Message)"
}

Write-Step "Summary"
Write-Host "  wfastcgi configured for Django on IIS" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "    1. Test Django: http://localhost/" -ForegroundColor White
Write-Host "    2. Test AI chat: http://localhost/ai/chat/" -ForegroundColor White
Write-Host "    3. Check logs: C:\inetpub\portal\logs\" -ForegroundColor White
Write-Host ""
Write-Host "=== wfastcgi configuration complete ===" -ForegroundColor Green
