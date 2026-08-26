# Операционный guide: AI UI protocol foundation

## Статус

Accepted. Матрица драйверов сокращена ADR-0032 до двух: `copilotkit`, `native`.
Драйвер `legacy` выведен из проекта; установка `LOCAL_BUSINESS_AI_UI_DRIVER=legacy`
падает с `ImproperlyConfigured` при старте.

## Назначение

Документ описывает, как включать и проверять общий AI UI слой. Основной целевой вариант - самописный UI в режиме `native`. CopilotKit остается отдельным равноправным драйвером и референсом AG-UI совместимости. Оба варианта используют один backend-контур.

## Драйверы

```text
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
LOCAL_BUSINESS_AI_UI_DRIVER=native
```

Поведение:

- `copilotkit` - React island + Copilot Runtime `/copilotkit`;
- `native` - основной самописный sidebar/full page через Django session-specific
  prepare/run и далее `agent-runtime /ag-ui`.

Если `LOCAL_BUSINESS_AI_UI_DRIVER` не задан, активен `native`.

Старый флаг `LOCAL_BUSINESS_COPILOTKIT_ENABLED=true` сохраняет совместимость и включает CopilotKit, если `LOCAL_BUSINESS_AI_UI_DRIVER` не задан явно.

## Проверка версии AG-UI

При изменениях серверной части AI UI обязательно проверить актуальность AG-UI профиля:

```bash
node -e "const p=require('./package.json'); console.log(p.dependencies['@ag-ui/client'])"
rg -n "LOCAL_BUSINESS_AI_UI_AGUI_PROFILE|ag-ui@" config docs package.json package-lock.json
```

Если изменение затрагивает `/ag-ui`, `services.agent_runtime.protocols`, `apps.ai.ui_runtime`, AI tools, Django AI gateway или deployment-профили, дополнительно сверить официальные release notes/docs AG-UI/CopilotKit. Результат по умолчанию - предупреждение в отчете: текущая версия актуальна или есть новая версия, но обновление не выполнялось.

Запрещено без согласования:

- менять `@ag-ui/client`;
- менять версии `@copilotkit/*`;
- менять `LOCAL_BUSINESS_AI_UI_AGUI_PROFILE`;
- менять wire contract событий только потому, что вышла новая версия.

После согласованного обновления версии обязательны unit/integration/e2e проверки по `copilotkit`, `native` и обновление ADR/guides/deployment.

## Native AG-UI chat

Native UI работает без Copilot Runtime:

```text
browser native sidebar/full page -> Django /ai/chat/<session>/turn/prepare/
                                -> Django /ai/chat/<session>/turn/run/
                                -> agent_runtime /ag-ui
CopilotKit Node runtime ---------------------------------> agent_runtime /ag-ui

`session_channel`, `presentation_surface` и `ui_driver` — отдельные поля
протокола; CopilotKit не вызывает native Django prepare/run endpoints.
```

Поддерживаемое поведение:

- config через `GET /ai/ui/config/`;
- новый чат через `POST /ai/ui/session/new/`;
- загрузка последних сообщений sidebar-сессии из Django history;
- выбор модели из `LOCAL_BUSINESS_AI_MODELS`;
- очистка текущего sidebar-чата через `POST /ai/ui/session/clear/`;
- ссылка на полный чат текущей сессии;
- stream parsing для `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`;
- сборка assistant message из `TEXT_MESSAGE_*`;
- compact tool trace из `TOOL_CALL_*` без raw sensitive payload;
- выполнение `STATE_DELTA /localBusiness/uiCommands` и `CUSTOM local_business.ui_command`;
- дедупликация UI-команд на клиенте;
- page context bridge через `LocalBusinessPageContext` только для native: Django
  включает его в подписанный execution payload. CopilotKit не получает dynamic
  unsigned `page_context`, пока не появится отдельный подписанный endpoint;
- сохранение user/assistant сообщений в Django `ChatSession`.

Перед выпуском применить `python manage.py migrate` для `ChatRun`. Prepare —
same-origin multipart с CSRF, проверкой владельца сессии и вложений; run получает
только подготовленные `threadId`/`runId`. `session_channel`,
`presentation_surface` и `ui_driver` проверяются отдельно. Повтор завершённого
`(session, run_id)` идемпотентен; недоступная модель возвращает безопасное
сообщение. Для SSE run reverse proxy должен отключать буферизацию.

Старые `send`/`stream`, `/ai/ui/ag-ui/run/`, runtime `/chat` и удалённые
`apps/ai/forms.py`/`static/src/js/ai_chat.js` не являются частью текущего
контура. После изменения native JS/CSS выполнить `python manage.py collectstatic
--noinput`, затем `python manage.py check_staticfiles --fail`.

Native assets подключаются с version query string:

```text
/static/src/ai_ui/native_ai.css?v=<version>
/static/src/ai_ui/native_ai.js?v=<version>
```

Service worker не должен cache-first обрабатывать `/static/src/ai_ui/`, иначе браузер может держать старый JS после deployment.

## Protocol contract

AG-UI stream должен содержать:

- `RUN_STARTED`;
- `CUSTOM name="local_business.protocol"`;
- `TEXT_MESSAGE_*`;
- `TOOL_CALL_*`, если были tools;
- `STATE_DELTA path="/localBusiness/uiCommands"`, если есть UI-команды;
- `RUN_FINISHED` или `RUN_ERROR`.

Переходная совместимость:

- `/localBusinessUiCommands` пока дублируется для CopilotKit island;
- новый основной путь: `/localBusiness/uiCommands`.

## Проверка режимов

CopilotKit:

```bash
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit .venv/bin/python manage.py runserver 127.0.0.1:8001
uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090
npm run copilot-runtime:start
```

Native:

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8001
uvicorn services.agent_runtime.app:app --host 127.0.0.1 --port 8090
```

Явная запись `LOCAL_BUSINESS_AI_UI_DRIVER=native` допустима, но для базового запуска не обязательна.

## Smoke checks

```bash
curl -fsS http://127.0.0.1:8001/health/
curl -fsS http://127.0.0.1:8090/health
```

Для CopilotKit дополнительно:

```bash
curl -fsS http://127.0.0.1:3100/health
```

## Обязательные проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native chat UX parity"
```

## Rollback

Драйвер `legacy` выведен из проекта (ADR-0032); откат к нему больше недоступен как
конфигурационная опция. Единственный путь отката - git-история (revert коммитов
пакета `09-legacy-ai-ui-driver-removal`).

Для CopilotKit можно остановить `copilot_runtime` и снять `/copilotkit` с reverse proxy,
а деплой переключить на `LOCAL_BUSINESS_AI_UI_DRIVER=native`. Для native rollback
используется предыдущий Git-релиз с его миграциями; параллельный legacy endpoint
не поддерживается.

## Безопасность

- Браузер не получает `LOCAL_BUSINESS_AI_GATEWAY_TOKEN`.
- Native UI не отправляет actor payload напрямую в agent runtime; Django proxy пересоздает подпись.
- Frontend выполняет только allow-listed UI-команды.
- Write tools остаются backend-only и проходят policies, confirmation и audit.
