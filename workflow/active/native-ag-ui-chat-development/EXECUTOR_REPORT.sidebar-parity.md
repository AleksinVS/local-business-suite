# Executor report: sidebar parity

## Статус

Выполнено.

## Сделано

- `/ai/ui/config/` теперь отдает для sidebar безопасный снимок последних сообщений, список моделей, текущий `model_id` и URL действий.
- Добавлен общий сервис `clear_sidebar_session`, который используется старым HTMX sidebar и новым native UI.
- Добавлен same-origin JSON endpoint `/ai/ui/session/clear/` для очистки текущей sidebar-сессии без смены thread.
- Native sidebar теперь:
  - восстанавливает историю после загрузки страницы;
  - показывает время сообщений;
  - показывает выбор модели из `LOCAL_BUSINESS_AI_MODELS`;
  - обновляет `ChatSession.metadata.model_id` через существующий endpoint модели;
  - очищает текущий чат с подтверждением;
  - показывает ссылку на полный чат текущей сессии.
- Playwright-сценарий `native chat UX parity` расширен проверкой модели, очистки и ссылки на полный чат.
- Unit-тесты покрывают config payload, JSON-очистку и совместимость старой HTMX-очистки.

## AG-UI version check

Проверено 2026-06-15:

```text
current @ag-ui/client=0.0.55
latest @ag-ui/client=0.0.57
current @copilotkit/runtime=1.59.5
latest @copilotkit/runtime=1.60.1
```

Решение: warning-only, зависимости и `agui_profile` не обновлялись.

## Проверки

Выполнено:

```bash
node --check static/src/ai_ui/native_ai.js
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_native_ai_ui_config_returns_signed_actor_payload apps.ai.tests.AIViewsTests.test_native_ai_ui_config_includes_sidebar_history_models_and_urls apps.ai.tests.AIViewsTests.test_native_ai_ui_new_session_returns_native_thread apps.ai.tests.AIViewsTests.test_native_ai_ui_clear_session_returns_clean_config apps.ai.tests.AIViewsTests.test_sidebar_chat_clear_deletes_sidebar_messages_and_summary --verbosity 2
.venv/bin/python manage.py test apps.ai.tests --verbosity 1
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
make gen-struct
E2E_AI_UI_DRIVER=native E2E_USERNAME=native-e2e-user E2E_PASSWORD=native-e2e-pass E2E_BASE_URL=http://127.0.0.1:8001 npm run test:e2e -- --project=chromium --grep "native chat UX parity"
```

Результаты:

- targeted AI UI tests: 5 tests OK;
- `apps.ai.tests`: 90 tests OK;
- `services.agent_runtime.tests.test_normalization`: 45 tests OK;
- `native chat UX parity` Playwright: 1 test passed.

Осталось перед финальным merge smoke:

```bash
git diff --check -- . ':(exclude)BACKLOG.md'
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
E2E_AI_UI_DRIVER=legacy npm run test:e2e -- --project=chromium --grep "context-aware sidebar"
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
```

## Остаточные риски

- Native full-page chat пока остается старой Django/HTMX страницей; отдельный task packet `06` должен заменить session management на native-вариант.
- Markdown, slash-команды и вложения для native rich input остаются в task packet `07`.
- AG-UI dependency update не выполнялся и требует отдельного согласования.
