@echo off
chdir /d C:\inetpub\portal
C:\inetpub\portal\.venv\Scripts\python.exe -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300
