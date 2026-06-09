# Deployment note: CopilotKit и AG-UI

## Статус

Accepted for pilot. Первый срез реализован, но production-включение требует отдельной приемки на целевом хосте.

## Назначение

CopilotKit не встраивается в Django-процесс. Для production-кандидата используется отдельный Copilot Runtime service, который проксирует AG-UI agent из `services.agent_runtime`.

## Целевые процессы

```text
Django web
agent_runtime FastAPI
copilot_runtime Node/HTTP
reverse proxy: Caddy/IIS
```

## Переменные окружения

Общие:

```text
LOCAL_BUSINESS_COPILOTKIT_ENABLED=false
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL=/copilotkit
LOCAL_BUSINESS_COPILOTKIT_AGENT_ID=local_business
LOCAL_BUSINESS_COPILOTKIT_ACTOR_TOKEN_TTL_SECONDS=900
LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL=http://agent-runtime:8090/ag-ui
LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION=1.0
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE=ag-ui@0.0.55
LOCAL_BUSINESS_AI_UI_ACTOR_TOKEN_TTL_SECONDS=900
COPILOTKIT_BASE_PATH=/copilotkit
COPILOTKIT_RUNTIME_PORT=3100
COPILOTKIT_TELEMETRY_DISABLED=true
```

Для service-to-service auth добавить отдельный секрет в приватный deployment repo:

```text
LOCAL_BUSINESS_COPILOTKIT_SERVICE_TOKEN=<secret>
```

Секреты не коммитить.

## Linux/VPS

Ожидаемая схема reverse proxy:

```text
/                  -> Django
/static/           -> static files
/copilotkit        -> copilot_runtime
/agent-runtime/    -> agent_runtime, только внутренняя сеть или admin-only
```

Health checks:

```bash
curl -fsS http://127.0.0.1:<django-port>/health/
curl -fsS http://127.0.0.1:8090/health
curl -fsS http://127.0.0.1:<copilot-port>/health
```

Минимальное правило сети:

- браузер видит Django и `/copilotkit`;
- `copilot_runtime` видит `agent_runtime`;
- `agent_runtime` видит Django AI gateway;
- браузер не должен напрямую обращаться к внутреннему Django AI gateway token endpoint.

## Windows/IIS

Для Windows/IIS deployment предпочтителен отдельный Windows service или Node process manager для Copilot Runtime.

Reverse proxy rules:

- основной Django FastCGI route остается без изменений;
- `/copilotkit` проксируется в Copilot Runtime;
- `/service-worker.js` и PWA routes не должны конфликтовать с CopilotKit bundle;
- long-running SSE responses должны быть разрешены для `/copilotkit`.

Перед включением pilot проверить timeout:

- IIS proxy timeout;
- FastCGI timeout Django;
- Copilot Runtime request timeout;
- agent runtime stream timeout.

## Static build

React island должен собираться в статические файлы проекта, например:

```text
static/dist/copilotkit/copilotkit-island.js
static/dist/copilotkit/copilotkit-island.css
```

Локальная сборка:

```bash
npm run build:copilotkit
```

Docker-образ `web` собирает этот bundle в отдельной Node-стадии и копирует результат в Python-образ. `static/dist/` не хранится в Git.

После изменения структуры:

```bash
make gen-struct
```

## Безопасность

Production default:

```text
COPILOTKIT_TELEMETRY_DISABLED=true
```

Не включать без отдельного решения:

- Copilot Cloud persistence;
- hosted analytics;
- external reinforcement learning;
- отправку raw state или full prompts во внешние сервисы.

Cookie/session rules:

- same-origin preferred;
- `credentials="include"` разрешать только при корректных CSRF/session настройках;
- cross-origin pilot требует отдельной CORS и CSRF модели.

## Rollback

1. Поставить `LOCAL_BUSINESS_AI_UI_DRIVER=legacy`.
2. Перезапустить Django web.
3. Убрать `/copilotkit` из reverse proxy или остановить `copilot_runtime`.
4. Проверить текущий AI sidebar.
5. Проверить, что `agent_runtime` продолжает отвечать `/chat/stream`.

## Проверка перед релизом

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
npm run test:e2e -- --project=chromium
```
