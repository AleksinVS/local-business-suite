param(
    [switch]$Setup,
    [switch]$Migrate,
    [switch]$SeedRoles,
    [switch]$StartRuntime,
    [switch]$WebOnly,
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [int]$RuntimePort = 8090
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $ProjectRoot ".env"
$EnvExampleFile = Join-Path $ProjectRoot ".env.example"
$RuntimeRequirements = Join-Path $ProjectRoot "services\agent_runtime\requirements.txt"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-PythonLauncher {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python launcher 'py' not found. Install Python 3.12+ and enable the launcher."
    }
}

function Ensure-Venv {
    if (-not (Test-Path $VenvPython)) {
        Write-Step "Creating virtual environment"
        & py -3 -m venv (Join-Path $ProjectRoot ".venv")
    }
}

function Ensure-EnvFile {
    if (-not (Test-Path $EnvFile)) {
        Write-Step "Creating .env from .env.example"
        Copy-Item $EnvExampleFile $EnvFile
    }
}

function Install-Requirements {
    Write-Step "Upgrading pip"
    & $VenvPython -m pip install --upgrade pip

    Write-Step "Installing Django app requirements"
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")

    Write-Step "Installing agent runtime requirements"
    & $VenvPython -m pip install -r $RuntimeRequirements
}

function Run-Migrate {
    Write-Step "Applying migrations"
    & $VenvPython (Join-Path $ProjectRoot "manage.py") migrate
}

function Run-SeedRoles {
    Write-Step "Seeding roles"
    & $VenvPython (Join-Path $ProjectRoot "manage.py") seed_roles
}

function Start-AgentRuntimeWindow {
    $Command = @(
        "Set-Location '$ProjectRoot'"
        "& '$VenvPython' -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port $RuntimePort --reload"
    ) -join "; "

    Write-Step "Starting agent runtime in a new PowerShell window"
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $Command
    ) | Out-Null
}

function Start-Web {
    Write-Step "Starting Django web server on http://$BindHost`:$Port"
    & $VenvPython (Join-Path $ProjectRoot "manage.py") runserver "$BindHost`:$Port"
}

Assert-PythonLauncher
Ensure-Venv
Ensure-EnvFile

if ($Setup) {
    Install-Requirements
}

if ($Migrate) {
    Run-Migrate
}

if ($SeedRoles) {
    Run-SeedRoles
}

if ($WebOnly) {
    Start-Web
    exit 0
}

if ($StartRuntime) {
    Start-AgentRuntimeWindow
}

Start-Web
