# Script to start agent runtime in background
# Uses relative paths to be deployment-agnostic
param(
    [string]$BindHost = "127.0.0.1",
    [int]$RuntimePort = 8090
)

$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    throw "Python виртуального окружения не найден: $VenvPython"
}

Set-Location $ProjectRoot
& $VenvPython -m uvicorn services.agent_runtime.app:app --host $BindHost --port $RuntimePort --timeout-keep-alive 300 --log-level info
