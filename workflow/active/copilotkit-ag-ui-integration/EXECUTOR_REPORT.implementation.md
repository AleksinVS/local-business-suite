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
- Добавлен Playwright e2e `scripts/e2e/tests/copilotkit_sidebar.spec.ts`.
- Старые HTMX sidebar e2e разделены с CopilotKit-режимом через `E2E_COPILOTKIT_ENABLED`.
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
- `E2E_BASE_URL=http://127.0.0.1:8001 E2E_USERNAME=chief_manager E2E_PASSWORD=... E2E_COPILOTKIT_ENABLED=true E2E_AGENT_RUNTIME_URL=http://127.0.0.1:8090 E2E_COPILOT_RUNTIME_URL=http://127.0.0.1:3100 npm run test:e2e -- --project=chromium` - 10 passed, 4 skipped
- `E2E_BASE_URL=http://127.0.0.1:8001 E2E_USERNAME=chief_manager E2E_PASSWORD=... E2E_AGENT_RUNTIME_URL=http://127.0.0.1:8090 E2E_COPILOT_RUNTIME_URL=http://127.0.0.1:3100 npm run test:e2e -- --project=chromium` - 13 passed, 1 skipped
- `npm audit --audit-level=high`
- `make gen-struct`
- `git diff --check -- . ':(exclude)BACKLOG.md'`

## Не выполнялось

- Реальный LLM-вызов через CopilotKit не выполнялся: локальный e2e проверял загрузку UI, signed config, health обоих runtime и принятие подписанного `/ag-ui` запроса без обращения к внешнему provider.
- Same-origin reverse proxy `/copilotkit` на целевом deployment не проверялся; локальный e2e использовал прямой `http://127.0.0.1:3100/copilotkit`.

## Остаточные риски

- CopilotKit bundle крупный; `static/dist/` не хранится в Git и должен собираться через `npm run build:copilotkit` или Docker build.
- `npm audit` оставляет low/moderate transitive уязвимости в `@copilotkit/runtime` tree; автоматическое исправление требует breaking downgrade.
- Production-приемка требует проверки reverse proxy, реального provider и пользовательского сценария с живым LLM.
