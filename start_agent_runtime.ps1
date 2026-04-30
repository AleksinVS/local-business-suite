# Script to start agent runtime in background
# Uses relative paths to be deployment-agnostic
$env:PYTHONUNBUFFERED = "1"
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
cd $scriptPath
.\.venv\Scripts\python.exe -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300 --log-level info
