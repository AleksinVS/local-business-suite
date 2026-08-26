# Deployment note: AI UI protocol foundation

## Статус

Accepted for pilot. Production-включение любого нового драйвера требует приемки на целевом хосте.

Основной целевой продуктовый режим - `native`: самописный AG-UI-compatible чат через Django same-origin proxy. `copilotkit` остается равноправным драйвером для сравнения, приемки AG-UI совместимости и fallback-пилота.

## Процессы по драйверам

Драйвер `legacy` выведен из проекта (ADR-0032); допустимая матрица - `copilotkit`, `native`.

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
browser native sidebar/full page -> Django /ai/chat/<session>/turn/prepare/
                                  -> Django /ai/chat/<session>/turn/run/
                                  -> agent_runtime /ag-ui
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

Если `LOCAL_BUSINESS_AI_UI_DRIVER` отсутствует, Django также выбирает `native`. Значение
`legacy` не поддерживается: Django падает при старте с `ImproperlyConfigured`.

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

Native execution requires `python manage.py migrate` (including `ChatRun`) before
traffic is enabled. Prepare is a same-origin CSRF-protected multipart request;
attachments are validated and stored with the user message. Their body is not yet
analysed by the model: only file name and type metadata are available to the
current chat flow. Run accepts only the prepared `threadId`/`runId`, checks session
ownership and channel/surface binding, and is idempotent for completed runs. An
unavailable model is exposed as a safe user-facing error. Disable reverse-proxy
buffering for the `text/event-stream` response from
`/ai/chat/<session>/turn/run/`.

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
- пройти e2e matrix для `copilotkit`, `native`;
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
/ai/chat/<session>/turn/prepare/ -> Django
/ai/chat/<session>/turn/run/     -> Django (SSE)
```

The removed legacy `send`, `stream`, `/ai/ui/ag-ui/run/` and runtime `/chat`
routes are not deployment targets. The deleted `apps/ai/forms.py` and
`static/src/js/ai_chat.js` must not be restored; the canonical browser flow is
`prepare` followed by `run`.

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
- `/ai/chat/<session>/turn/run/` stream не буферизуется reverse proxy;
- user/assistant messages сохраняются в Django `ChatSession`;
- browser не получает прямой доступ к `agent_runtime`.
- после изменения native assets выполнить `python manage.py collectstatic --noinput`
  и проверить согласованность через `python manage.py check_staticfiles --fail`;
- dynamic page context передаётся только native-клиентом в Django prepare/run;
  CopilotKit получает только серверно подписанные свойства, без unsigned
  dynamic `page_context`.

## Rollback

Драйвер `legacy` выведен из проекта (ADR-0032) и не является допустимым значением для
`LOCAL_BUSINESS_AI_UI_DRIVER`. Rollback выполняется возвратом на предыдущий Git-релиз
с его миграциями и перезапуском Django web; параллельный legacy endpoint не поддерживается.
Для CopilotKit можно дополнительно остановить `copilot_runtime`.

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
