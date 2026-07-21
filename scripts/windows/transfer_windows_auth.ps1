# Transfer Windows Authentication Settings Between IIS Hosts
# Transfers only Windows Authentication settings between IIS hosts
# without a full migration bundle.
#
# Usage:
#   .\transfer_windows_auth.ps1 -Export -SiteName portal -OutputFile C:\temp\win-auth.xml
#   .\transfer_windows_auth.ps1 -Import -SiteName portal -InputFile C:\temp\win-auth.xml
#   .\transfer_windows_auth.ps1 -ShowCurrent -SiteName portal

[CmdletBinding(DefaultParameterSetName = 'Show')]
param(
    [Parameter(ParameterSetName = 'Export', Mandatory = $true)]
    [switch]$Export,

    [Parameter(ParameterSetName = 'Import', Mandatory = $true)]
    [switch]$Import,

    [Parameter(ParameterSetName = 'Show')]
    [switch]$ShowCurrent,

    [string]$SiteName = "portal",

    [Parameter(ParameterSetName = 'Export')]
    [string]$OutputFile = ".\win-auth.xml",

    [Parameter(ParameterSetName = 'Import')]
    [string]$InputFile = ".\win-auth.xml"
)

$ErrorActionPreference = "Stop"

# --- Self-elevate to admin ---------------------------------------------------
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

# --- Helpers -----------------------------------------------------------------
function Write-Step($name) { Write-Host ""; Write-Host "[$name]" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  !   $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "  X   $msg" -ForegroundColor Red }

function Get-AuthState {
    param([string]$Site)
    $state = @{}
    try {
        # For scalar attributes (Enabled, useKernelMode) Get-WebConfigurationProperty returns
        # a ConfigurationAttribute object — use .Value to get the actual bool/string.
        $winAuthAttr = Get-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" -PSPath "IIS:\Sites\$Site" -Name "Enabled"
        $state.WinAuth = if ($winAuthAttr) { $winAuthAttr.Value } else { $null }

        try {
            $kernelAttr = Get-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" -PSPath "IIS:\Sites\$Site" -Name "useKernelMode" -ErrorAction SilentlyContinue
            $state.UseKernelMode = if ($kernelAttr) { $kernelAttr.Value } else { $null }
        } catch { $state.UseKernelMode = $null }

        $anonAttr = Get-WebConfigurationProperty -Filter "/system.webServer/security/authentication/anonymousAuthentication" -PSPath "IIS:\Sites\$Site" -Name "Enabled" -ErrorAction SilentlyContinue
        $state.Anonymous = if ($anonAttr) { $anonAttr.Value } else { $null }

        $basicAttr = Get-WebConfigurationProperty -Filter "/system.webServer/security/authentication/basicAuthentication" -PSPath "IIS:\Sites\$Site" -Name "Enabled" -ErrorAction SilentlyContinue
        $state.Basic = if ($basicAttr) { $basicAttr.Value } else { $null }

        $digestAttr = Get-WebConfigurationProperty -Filter "/system.webServer/security/authentication/digestAuthentication" -PSPath "IIS:\Sites\$Site" -Name "Enabled" -ErrorAction SilentlyContinue
        $state.Digest = if ($digestAttr) { $digestAttr.Value } else { $null }

        # Providers is a collection of <add value="..."/> child elements.
        try {
            $providerCol = Get-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication/providers/add" -PSPath "IIS:\Sites\$Site" -Name "value" -ErrorAction SilentlyContinue
            if ($providerCol) {
                $provList = @()
                foreach ($p in $providerCol) {
                    if ($p -is [string]) { $provList += $p }
                    elseif ($p.Value)    { $provList += [string]$p.Value }
                }
                $state.WinProviders = $provList
            } else {
                $state.WinProviders = @()
            }
        } catch { $state.WinProviders = @() }
    } catch {
        Write-Warn "cannot read authentication state for site '$Site'"
    }
    return $state
}

function Show-AuthState {
    param([string]$Label, [hashtable]$State)
    Write-Host "  $Label" -ForegroundColor Cyan
    Write-Host "    Windows Authentication: $($State.WinAuth)" -ForegroundColor Gray
    if ($State.WinProviders -and $State.WinProviders.Count -gt 0) {
        Write-Host "    Providers:               $($State.WinProviders -join ', ')" -ForegroundColor Gray
    }
    Write-Host "    Anonymous:               $($State.Anonymous)" -ForegroundColor Gray
    Write-Host "    Basic:                   $($State.Basic)" -ForegroundColor Gray
    Write-Host "    Digest:                  $($State.Digest)" -ForegroundColor Gray
    if ($null -ne $State.UseKernelMode) { Write-Host "    useKernelMode:           $($State.UseKernelMode)" -ForegroundColor Gray }
}

# --- Init -------------------------------------------------------------------
Import-Module WebAdministration -ErrorAction Stop

Write-Host "=== Transfer Windows Authentication ===" -ForegroundColor Cyan
Write-Host ""

# --- Mode: show current state ------------------------------------------------
if ($ShowCurrent) {
    Write-Step "Current IIS state: $SiteName"
    if (-not (Test-Path "IIS:\Sites\$SiteName")) {
        Write-Fail "Site '$SiteName' not found in IIS"
        exit 1
    }
    $state = Get-AuthState -Site $SiteName
    Show-AuthState -Label "Current settings:" -State $state
    exit 0
}

# --- Mode: EXPORT -----------------------------------------------------------
if ($Export) {
    Write-Step "Check site"
    if (-not (Test-Path "IIS:\Sites\$SiteName")) {
        Write-Fail "Site '$SiteName' not found in IIS"
        Write-Host "Available sites:" -ForegroundColor Yellow
        Get-Website | ForEach-Object { Write-Host "  - $($_.Name)" -ForegroundColor Gray }
        exit 1
    }
    Write-Ok "Site found: $SiteName"

    Write-Step "Export authentication settings"
    $state = Get-AuthState -Site $SiteName
    Show-AuthState -Label "Source state:" -State $state

    # Build XML via here-string (no < redirection issues, no quote escaping)
    $winAuthEnabled = if ($state.WinAuth) { "true" } else { "false" }
    $anonEnabled = if ($state.Anonymous) { "true" } else { "false" }
    $basicEnabled = if ($state.Basic) { "true" } else { "false" }
    $digestEnabled = if ($state.Digest) { "true" } else { "false" }

    $providersLine = ""
    if ($state.WinProviders -and $state.WinProviders.Count -gt 0) {
        $providersStr = $state.WinProviders -join ","
        $providersLine = "    <providers value=`"$providersStr`" />"
    }

    $kernelLine = ""
    if ($null -ne $state.UseKernelMode) {
        $kernelVal = if ($state.UseKernelMode) { "true" } else { "false" }
        $kernelLine = "    <windowsAuth useKernelMode=`"$kernelVal`" />"
    }

    $xml = @"
<windowsAuthExport site="$SiteName" exported="$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')">
  <authentication>
    <windowsAuthentication enabled="$winAuthEnabled" />
$providersLine
    <anonymousAuthentication enabled="$anonEnabled" />
    <basicAuthentication enabled="$basicEnabled" />
    <digestAuthentication enabled="$digestEnabled" />
$kernelLine
  </authentication>
</windowsAuthExport>
"@

    # Make path absolute (important under self-elevation)
    $outputPath = $OutputFile
    if (-not [System.IO.Path]::IsPathRooted($outputPath)) {
        $scriptRoot = Split-Path -Parent $PSCommandPath
        if (-not $scriptRoot) { $scriptRoot = (Get-Location).Path }
        $outputPath = Join-Path $scriptRoot $outputPath.TrimStart(".\")
    }
    $outputDir = Split-Path -Parent $outputPath
    if ($outputDir -and -not (Test-Path $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }

    # Write UTF-8 without BOM
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($outputPath, $xml, $enc)
    Write-Ok "Export saved: $outputPath"

    Write-Step "Next steps"
    Write-Host "  1. Copy the file to target host" -ForegroundColor White
    Write-Host "  2. Run import:" -ForegroundColor White
    Write-Host "     .\transfer_windows_auth.ps1 -Import -SiteName $SiteName -InputFile <path-to-win-auth.xml>" -ForegroundColor Gray
    exit 0
}

# --- Mode: IMPORT -----------------------------------------------------------
if ($Import) {
    Write-Step "Check input file"
    if (-not (Test-Path $InputFile)) {
        Write-Fail "Input file not found: $InputFile"
        exit 1
    }
    Write-Ok "Input file: $InputFile"

    # Strip possible BOM
    $xmlContent = Get-Content $InputFile -Raw
    $xmlContent = $xmlContent.TrimStart([char]0xFEFF)

    try {
        [xml]$doc = $xmlContent
    } catch {
        Write-Fail "Failed to parse XML: $($_.Exception.Message)"
        exit 1
    }

    $siteFromXml = $doc.windowsAuthExport.site
    if (-not $siteFromXml) { $siteFromXml = $SiteName }
    Write-Host "  Site from XML: $siteFromXml" -ForegroundColor Gray

    Write-Step "Check target site"
    if (-not (Test-Path "IIS:\Sites\$SiteName")) {
        Write-Fail "Site '$SiteName' not found in IIS on this host"
        Write-Host "Create the site first (e.g. via import_portal.ps1)" -ForegroundColor Yellow
        exit 1
    }
    Write-Ok "Site found: $SiteName"

    # Unlock authentication sections at server level (overrideModeDefault="Deny"
    # blocks per-site override on a fresh IIS install — must unlock before set).
    Write-Step "Unlock authentication sections"
    $appcmd = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"
    $sections = @(
        "system.webServer/security/authentication/windowsAuthentication",
        "system.webServer/security/authentication/anonymousAuthentication",
        "system.webServer/security/authentication/basicAuthentication",
        "system.webServer/security/authentication/digestAuthentication"
    )
    foreach ($sec in $sections) {
        try {
            & $appcmd unlock config -section:$sec 2>&1 | Out-Null
            Write-Ok "unlocked: $sec"
        } catch {
            Write-Warn "unlock failed: $sec ($($_.Exception.Message))"
        }
    }

    # State BEFORE
    $beforeState = Get-AuthState -Site $SiteName
    Show-AuthState -Label "State BEFORE import:" -State $beforeState

    Write-Step "Applying settings"

    $auth = $doc.windowsAuthExport.authentication
    $changed = $false
    $winEnabled = $false

    # Windows Authentication
    $winNode = $auth.SelectSingleNode("windowsAuthentication[@enabled]")
    if ($winNode) {
        $winEnabled = $winNode.GetAttribute("enabled") -eq "true"
        Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" `
            -PSPath "IIS:\Sites\$SiteName" -Name "Enabled" -Value $winEnabled
        Write-Ok "Windows Authentication: $winEnabled"
        $changed = $true

        # useKernelMode
        $kernelNode = $auth.SelectSingleNode("windowsAuth[@useKernelMode]")
        if ($kernelNode) {
            $kernelMode = $kernelNode.GetAttribute("useKernelMode") -eq "true"
            try {
                Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" `
                    -PSPath "IIS:\Sites\$SiteName" -Name "useKernelMode" -Value $kernelMode
                Write-Ok "useKernelMode: $kernelMode"
            } catch { Write-Warn "useKernelMode not set: $($_.Exception.Message)" }
        }
    }

    # Providers
    $providersNode = $auth.SelectSingleNode("providers[@value]")
    if ($providersNode -and $winEnabled) {
        $providers = $providersNode.GetAttribute("value") -split ","
        Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" `
            -PSPath "IIS:\Sites\$SiteName" -Name "Providers" -Value $providers
        Write-Ok "Providers: $($providers -join ', ')"
    }

    # Anonymous
    $anonNode = $auth.SelectSingleNode("anonymousAuthentication[@enabled]")
    if ($anonNode) {
        $anonEnabled = $anonNode.GetAttribute("enabled") -eq "true"
        Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/anonymousAuthentication" `
            -PSPath "IIS:\Sites\$SiteName" -Name "Enabled" -Value $anonEnabled
        Write-Ok "Anonymous Authentication: $anonEnabled"
    }

    # Basic
    $basicNode = $auth.SelectSingleNode("basicAuthentication[@enabled]")
    if ($basicNode) {
        $basicEnabled = $basicNode.GetAttribute("enabled") -eq "true"
        try {
            Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/basicAuthentication" `
                -PSPath "IIS:\Sites\$SiteName" -Name "Enabled" -Value $basicEnabled
            Write-Ok "Basic Authentication: $basicEnabled"
        } catch { Write-Warn "Basic Authentication: $($_.Exception.Message)" }
    }

    # Digest
    $digestNode = $auth.SelectSingleNode("digestAuthentication[@enabled]")
    if ($digestNode) {
        $digestEnabled = $digestNode.GetAttribute("enabled") -eq "true"
        try {
            Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/digestAuthentication" `
                -PSPath "IIS:\Sites\$SiteName" -Name "Enabled" -Value $digestEnabled
            Write-Ok "Digest Authentication: $digestEnabled"
        } catch { Write-Warn "Digest Authentication: $($_.Exception.Message)" }
    }

    if (-not $changed) {
        Write-Warn "No windowsAuthentication settings found in XML - nothing applied"
    }

    # State AFTER
    $afterState = Get-AuthState -Site $SiteName
    Write-Step "Result"
    Show-AuthState -Label "State AFTER import:" -State $afterState

    Write-Step "Verification"
    Write-Host "  Open IIS Manager -> $SiteName -> Authentication" -ForegroundColor Gray
    Write-Host "  or check WWW-Authenticate headers:" -ForegroundColor Gray
    Write-Host "    curl -I http://localhost/ --ntlm -u :" -ForegroundColor Gray

    Write-Host ""
    Write-Host "=== Windows Authentication import complete ===" -ForegroundColor Green
    exit 0
}

# --- Neither Export nor Import specified -------------------------------------
Write-Fail "Specify mode: -Export or -Import"
Write-Host "  Export:  .\transfer_windows_auth.ps1 -Export -SiteName portal -OutputFile win-auth.xml" -ForegroundColor Yellow
Write-Host "  Import:  .\transfer_windows_auth.ps1 -Import -SiteName portal -InputFile win-auth.xml" -ForegroundColor Yellow
Write-Host "  Check:   .\transfer_windows_auth.ps1 -ShowCurrent -SiteName portal" -ForegroundColor Yellow
exit 1
