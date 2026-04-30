# Инструкция по созданию Windows Service для Agent Runtime

## Проблема
AI-агент выдает ошибку при отправке сообщения, потому что Agent Runtime не запущен как служба.

## Решение
Создать Windows Service с помощью NSSM (Non-Sucking Service Manager)

## Шаги:

### 1. Скачать и установить NSSM
- Скачать: https://nssm.cc/download
- Распаковать в папку, например: C:\nssm
- Добавить C:\nssm в PATH или использовать полный путь

### 2. Создать службу
```powershell
# Откройте PowerShell от имени администратора и выполните:
cd C:\nssm
nssm install AgentRuntime C:\inetpub\portal\.venv\Scripts\python.exe
```

### 3. Настроить службу
```powershell
nssm set AgentRuntime AppParameters "-m" "uvicorn" "services.agent_runtime.app:app" "--host" "127.0.0.1" "--port" "8090" "--timeout-keep-alive" "300"
nssm set AgentRuntime AppDirectory C:\inetpub\portal
nssm set AgentRuntime DisplayName "Portal Agent Runtime"
nssm set AgentRuntime Description "AI Agent Runtime for Corporate Portal"
nssm set AgentRuntime Start SERVICE_AUTO_START
nssm set AgentRuntime AppEnvironmentExtra "PYTHONUNBUFFERED=1"
```

### 4. Запустить службу
```powershell
nssm start AgentRuntime
```

### 5. Проверить работу службы
```powershell
# Проверить статус
nssm status AgentRuntime

# Проверить health endpoint
Invoke-RestMethod -Uri "http://127.0.0.1:8090/health"
```

### 6. Управление службой
```powershell
# Остановить
nssm stop AgentRuntime

# Перезапустить
nssm restart AgentRuntime

# Удалить (если нужно)
nssm remove AgentRuntime confirm
```

## Временное решение (без создания службы)

Для быстрого тестирования можно запустить вручную:
```powershell
cd C:\inetpub\portal
.\.venv\Scripts\python.exe -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300
```

## Исправленные настройки в .env

Файл `.env` был обновлен с правильными настройками:
```bash
OPENAI_API_KEY=aa0064be33c74dd1842ddbe07c214b1b.UP7Hz4Z4w9srIuMU
OPENAI_BASE_URL=https://api.z.ai/api/coding/paas/v4/
AI_AGENT_MODEL_NAME=glm-4.5-air
DJANGO_AI_GATEWAY_URL=http://localhost/ai/gateway
```

## Исправленные файлы

1. `services/agent_runtime/config.py` - добавлена загрузка .env файла
2. `services/agent_runtime/prompting.py` - исправлен отступ в return
3. `.env` - исправлены настройки OPENAI_BASE_URL и AI_AGENT_MODEL_NAME
