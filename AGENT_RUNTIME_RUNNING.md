# ✅ Agent Runtime успешно запущен!

Agent Runtime теперь работает на порту 8090.

## Текущий статус:
- **Статус**: ✓ OK
- **Модель**: openai:glm-4.5-air
- **Gateway**: http://localhost/ai/gateway
- **API ключ**: ✓ Настроен
- **Порт**: 8090

## Временное решение (запущено сейчас):

Agent Runtime запущен в отдельном окне. Если вы закроете это окно, сервис остановится.

## Постоянное решение - создать Windows Service:

### 1. Скачайте NSSM (Non-Sucking Service Manager)
- Ссылка: https://nssm.cc/download
- Распакуйте в папку, например: `C:\nssm`

### 2. Создайте службу (запустите PowerShell от имени администратора):

```powershell
cd C:\nssm
nssm install PortalAgentRuntime "C:\inetpub\portal\.venv\Scripts\python.exe"
```

### 3. Настройте параметры службы:

```powershell
# Установите параметры запуска
nssm set PortalAgentRuntime AppParameters "-m" "uvicorn" "services.agent_runtime.app:app" "--host" "127.0.0.1" "--port" "8090" "--timeout-keep-alive" "300"

# Установите рабочую директорию
nssm set PortalAgentRuntime AppDirectory "C:\inetpub\portal"

# Настройте отображаемое имя
nssm set PortalAgentRuntime DisplayName "Portal Agent Runtime"

# Добавьте описание
nssm set PortalAgentRuntime Description "AI Agent Runtime for Corporate Portal"

# Автоматический запуск при старте системы
nssm set PortalAgentRuntime Start SERVICE_AUTO_START

# Добавьте переменную окружения
nssm set PortalAgentRuntime AppEnvironmentExtra "PYTHONUNBUFFERED=1"

# Настройте перезапуск при сбоях
nssm set PortalAgentRuntime AppExit Default Restart
nssm set PortalAgentRuntime AppRestartDelay 5000
```

### 4. Запустите службу:

```powershell
nssm start PortalAgentRuntime
```

### 5. Проверьте работу службы:

```powershell
# Проверить статус
nssm status PortalAgentRuntime

# Проверить health endpoint
Invoke-RestMethod -Uri "http://127.0.0.1:8090/health"
```

## Управление службой:

```powershell
# Остановить службу
nssm stop PortalAgentRuntime

# Перезапустить службу
nssm restart PortalAgentRuntime

# Удалить службу (если нужно)
nssm remove PortalAgentRuntime confirm

# Открыть редактор настроек
nssm edit PortalAgentRuntime
```

## Быстрая проверка работоспособности AI-чата:

1. Откройте портал: http://localhost/
2. Перейдите в раздел AI Chat: http://localhost/ai/chat/
3. Отправьте тестовое сообщение

AI-агент должен ответить, используя модель GLM-4.5-air от Z.ai!

## Если служба не запускается:

### Проверьте логи:

```powershell
# Через NSSM
nssm get PortalAgentRuntime AppStdout
nssm get PortalAgentRuntime AppStderr

# Или вручную запустите и посмотрите ошибки
cd "C:\inetpub\portal"
.\.venv\Scripts\python.exe -m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300
```

### Частые проблемы:

1. **Порт занят**: Измените порт на 8091 или другой свободный порт
2. **Python не найден**: Проверьте путь к python.exe
3. **Модули не установлены**: Установите зависимости:
   ```powershell
   cd "C:\inetpub\portal"
   .\.venv\Scripts\python.exe -m pip install uvicorn fastapi langchain langgraph langchain-openai mcp
   ```

## Временный запуск без службы (для тестирования):

```powershell
cd "C:\inetpub\portal"
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "services.agent_runtime.app:app", "--host", "127.0.0.1", "--port", "8090", "--timeout-keep-alive", "300" -WindowStyle Normal
```

## Автоматический запуск через Task Scheduler (альтернатива):

Если не хотите создавать службу, можно использовать планировщик задач:

1. Откройте Task Scheduler (taskschd.msc)
2. Create Task → Triggers → "At startup"
3. Actions → Start program:
   - Program: `C:\inetpub\portal\.venv\Scripts\python.exe`
   - Arguments: `-m uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090 --timeout-keep-alive 300`
   - Start in: `C:\inetpub\portal`
