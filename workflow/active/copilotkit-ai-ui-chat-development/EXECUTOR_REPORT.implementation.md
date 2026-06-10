# Executor report: implementation

## Scope

Первый runtime hardening срез для режима:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit
```

## Изменения

- добавлен endpoint `POST /ai/ui/session/new/`;
- добавлена CopilotKit-страница `GET /ai/chat/copilotkit/`;
- `/ai/chat/` в режиме `copilotkit` больше не ведет на старый Django chat detail;
- добавлено создание новой sidebar-сессии с архивацией предыдущей активной сессии;
- CopilotKit React island получил кнопку нового чата и remount по новому `thread_id`;
- page context стал реактивным через событие `ai-context:update`;
- `/ag-ui` теперь отдает AG-UI `RUN_ERROR` при отсутствующем `OPENAI_API_KEY`, а не HTTP 503 до начала stream;
- tool trace рекурсивно маскирует sensitive args;
- UI-команды ограничены allow-list, безопасным URL, mode/swap и размером batch;
- e2e smoke проверяет создание нового CopilotKit thread.

## Измененные файлы

- `apps/ai/services.py`;
- `apps/ai/views.py`;
- `apps/ai/urls.py`;
- `templates/base.html`;
- `templates/ai/copilotkit_chat.html`;
- `static/src/copilotkit/main.jsx`;
- `static/src/copilotkit/copilotkit.css`;
- `services/agent_runtime/app.py`;
- `services/agent_runtime/protocols/agui/v1.py`;
- `services/agent_runtime/protocols/common/ui_commands.py`;
- `apps/ai/tests.py`;
- `services/agent_runtime/tests/test_normalization.py`;
- `scripts/e2e/tests/copilotkit_sidebar.spec.ts`;
- `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/planning/active/copilotkit-ai-ui-chat-development.md`;
- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`.

## Проверки

Выполнено:

```bash
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_ai_ui_new_session_creates_clean_copilotkit_thread apps.ai.tests.AIViewsTests.test_copilotkit_config_returns_signed_actor_payload
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization.TestAGUIAdapter services.agent_runtime.tests.test_normalization.TestAGUIRuntimeEndpoint -v
node --check services/copilot_runtime/server.mjs
npm run build:copilotkit
```

Дополнительно выполнено:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
E2E_BASE_URL=http://127.0.0.1:8001 E2E_USERNAME=chief_manager E2E_PASSWORD='HospitalDemo-2026!' E2E_AI_UI_DRIVER=copilotkit E2E_AGENT_RUNTIME_URL=http://127.0.0.1:8090 E2E_COPILOT_RUNTIME_URL=http://127.0.0.1:3100 npm run test:e2e -- --project=chromium --grep "CopilotKit AG-UI sidebar"
git diff --check -- . ':(exclude)BACKLOG.md'
```

Результат:

- `apps.ai.tests`: 82 tests OK;
- `services.agent_runtime.tests.test_normalization`: 45 tests OK;
- CopilotKit Playwright e2e: 2 passed;
- Django, Agent Runtime и Copilot Runtime health endpoints отвечают локально.

## Остаточный риск

- Требуется проверка `/copilotkit` reverse proxy и SSE timeout на целевом deployment.
- Требуется ручной prompt/response сценарий при настроенном `OPENAI_API_KEY`.
- Исторический список CopilotKit-сессий в UI пока не реализован как отдельный пользовательский экран.
