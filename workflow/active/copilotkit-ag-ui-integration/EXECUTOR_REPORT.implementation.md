# Executor Report: implementation

Дата: 2026-06-09.

## Scope

Реализован первый срез CopilotKit/AG-UI в отдельной ветке без замены текущего Django/HTMX sidebar.

## Выполнено

- Добавлен AG-UI endpoint `POST /ag-ui` в `services.agent_runtime`.
- Добавлен тестируемый mapper AG-UI событий в `services/agent_runtime/ag_ui_adapter.py`.
- Добавлена проверка HMAC-подписи actor/session payload перед вызовом агента.
- Добавлен Django endpoint `ai:copilotkit_config` для выдачи feature-flagged конфигурации React-острова.
- Добавлен React-остров `static/src/copilotkit/main.jsx` с `CopilotChat` и мостом `STATE_DELTA -> LocalBusinessRightPanel.open`.
- Добавлен Node-сервис `services/copilot_runtime/server.mjs` с CopilotKit Runtime v2 и AG-UI `HttpAgent`.
- Добавлены npm-скрипты `build:copilotkit` и `copilot-runtime:start`.
- Добавлен Docker build path: web-образ собирает CopilotKit bundle в Node-стадии, `copilot-runtime` запускается отдельным сервисом.
- Обновлены настройки, `.env.example`, deployment, operations, ADR, planning, backlog, `.desc.json` и `PROJECT_STRUCTURE.yaml`.

## Проверки

Пройдены:

- `python -m py_compile apps/ai/context_processors.py apps/ai/views.py services/agent_runtime/ag_ui_adapter.py services/agent_runtime/app.py services/agent_runtime/schemas.py`
- `node --check services/copilot_runtime/server.mjs`
- `npm run build:copilotkit`
- `python manage.py check`
- `python manage.py validate_architecture_contracts`
- `python -m unittest services.agent_runtime.tests.test_normalization -v`
- `python manage.py test apps.ai.tests --keepdb -v 1`
- `curl -fsS http://127.0.0.1:3100/health` при запущенном `npm run copilot-runtime:start`
- `npm audit --audit-level=high`
- `make gen-struct`
- `git diff --check -- . ':(exclude)BACKLOG.md'`

## Не выполнялось

- Авторизованный Playwright e2e не запускался: в текущей среде не задан стенд с `E2E_USERNAME`/`E2E_PASSWORD` и включенным `LOCAL_BUSINESS_COPILOTKIT_ENABLED=true`.
- Реальный LLM-вызов через CopilotKit не выполнялся: это требует `OPENAI_API_KEY`/целевого provider и запущенной связки Django + agent runtime + Copilot Runtime.

## Остаточные риски

- CopilotKit bundle крупный; `static/dist/` не хранится в Git и должен собираться через `npm run build:copilotkit` или Docker build.
- `npm audit` оставляет low/moderate transitive уязвимости в `@copilotkit/runtime` tree; автоматическое исправление требует breaking downgrade.
- Полная пользовательская приемка требует e2e на стенде с включенным feature flag.
