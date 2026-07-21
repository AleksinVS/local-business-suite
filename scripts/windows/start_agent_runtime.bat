@echo off
set "PROJECT_ROOT=%~dp0..\.."
pushd "%PROJECT_ROOT%"
if not exist ".venv\Scripts\python.exe" (
    echo Python virtual environment not found: %CD%\.venv\Scripts\python.exe
    popd
    exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300 --log-level info
popd
