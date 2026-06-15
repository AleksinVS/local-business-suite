# Deployment note: AI UI protocol foundation

## Статус

Accepted for pilot. Production-включение любого нового драйвера требует приемки на целевом хосте.

Основной целевой продуктовый режим - `native`: самописный AG-UI-compatible чат через Django same-origin proxy. `copilotkit` остается равноправным драйвером для сравнения, приемки AG-UI совместимости и fallback-пилота.

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
LOCAL_BUSINESS_AI_UI_DRIVER=native
LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION=1.0
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE=ag-ui@0.0.55
LOCAL_BUSINESS_AI_UI_ACTOR_TOKEN_TTL_SECONDS=900
LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://agent-runtime:8090
LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL=http://agent-runtime:8090/ag-ui
```

Если `LOCAL_BUSINESS_AI_UI_DRIVER` отсутствует, Django также выбирает `native`. `legacy` задается явно только для rollback.

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

## Контроль версии AG-UI

Production deployment должен держать согласованными:

```text
package.json: @ag-ui/client
package-lock.json: @ag-ui/client
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE
protocol metadata: agui_profile
```

Перед изменением backend-контура AI UI нужно проверить актуальность AG-UI версии. Если появилась новая версия, это фиксируется как предупреждение и риск релиза. Обновление версии не входит в обычный deployment и выполняется только после согласования с владельцем.

Согласованное обновление версии требует:

- обновить `@ag-ui/client`, связанные `@copilotkit/*` зависимости, если это необходимо, и `LOCAL_BUSINESS_AI_UI_AGUI_PROFILE`;
- проверить `/ag-ui` stream и protocol metadata;
- пройти e2e matrix для `legacy`, `copilotkit`, `native`;
- проверить rollback на `LOCAL_BUSINESS_AI_UI_DRIVER=legacy`;
- обновить ADR, operations guide и deployment note.

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

## Static/PWA для native UI

Native AI UI использует исходные static assets:

```text
/static/src/ai_ui/native_ai.css
/static/src/ai_ui/native_ai.js
```

HTML должен подключать их с version query string. Root service worker должен пропускать `/static/src/ai_ui/` без cache-first обработки. Это нужно, чтобы после deployment браузер не оставался на старом AG-UI reducer.

При production-включении `native` проверить:

- `/ai/ui/config/` доступен authenticated-пользователю;
- `/ai/ui/session/new/` создает новый sidebar thread;
- `/ai/ui/ag-ui/run/` stream не буферизуется reverse proxy;
- user/assistant messages сохраняются в Django `ChatSession`;
- browser не получает прямой доступ к `agent_runtime`.

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
