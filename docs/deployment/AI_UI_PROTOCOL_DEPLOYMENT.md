# Deployment note: AI UI protocol foundation

## Статус

Accepted for pilot. Production-включение любого нового драйвера требует приемки на целевом хосте.

## Процессы по драйверам

### `legacy`

```text
Django web
agent_runtime FastAPI
```

Дополнительный Node-процесс не нужен.

### `copilotkit`

```text
Django web
agent_runtime FastAPI
copilot_runtime Node/HTTP
reverse proxy /copilotkit -> copilot_runtime
```

### `native`

```text
Django web
agent_runtime FastAPI
browser -> Django /ai/ui/ag-ui/run/ -> agent_runtime /ag-ui
```

Copilot Runtime не нужен. Браузер работает same-origin с Django.

## Переменные окружения

Общие:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION=1.0
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE=ag-ui@0.0.55
LOCAL_BUSINESS_AI_UI_ACTOR_TOKEN_TTL_SECONDS=900
LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090
LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL=http://agent-runtime:8090/ag-ui
```

CopilotKit:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL=/copilotkit
LOCAL_BUSINESS_COPILOTKIT_AGENT_ID=local_business
COPILOTKIT_BASE_PATH=/copilotkit
COPILOTKIT_RUNTIME_PORT=3100
COPILOTKIT_TELEMETRY_DISABLED=true
```

Native:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=native
```

## Reverse proxy

Общие маршруты:

```text
/          -> Django
/static/   -> static files
```

CopilotKit:

```text
/copilotkit -> copilot_runtime
```

Native:

```text
/ai/ui/ag-ui/run/ -> Django
```

Для native отдельный внешний route к `agent_runtime` не нужен.

## Rollback

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
```

После изменения перезапустить Django web. Для CopilotKit можно дополнительно остановить `copilot_runtime`.

## Проверка перед включением

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
npm run test:e2e -- --project=chromium
```
