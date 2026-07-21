# Executor report: implementation

## Статус

Выполнено.

## Сделано

- Исправлен native mount в `templates/base.html`: используется `/ai/ui/config/` и `/ai/ui/session/new/`.
- Добавлен `native_ai_asset_version` и version query string для native JS/CSS.
- Service worker больше не cache-first обрабатывает `/static/src/ai_ui/`.
- `static/src/ai_ui/native_ai.js` заменен на AG-UI-compatible client reducer:
  - новый чат;
  - `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`;
  - `TEXT_MESSAGE_*`;
  - `TOOL_CALL_*`;
  - `STATE_SNAPSHOT`, `STATE_DELTA`;
  - `CUSTOM local_business.protocol`;
  - `CUSTOM local_business.ui_command`;
  - unknown events ignore.
- Добавлен compact tool trace без raw sensitive payload.
- Django native proxy теперь:
  - сохраняет user message перед stream;
  - привязывает page context snapshot;
  - передает trace context в actor payload;
  - подмешивает Django history в AG-UI request;
  - сохраняет assistant/error message после stream;
  - сохраняет `tool_trace`, `ui_commands`, `conversation_id`, `request_id`.
- Расширены unit и Playwright e2e проверки.
- Обновлены operations/deployment docs.

## AG-UI version check

Проверено 2026-06-10:

```text
current @ag-ui/client=0.0.55
latest @ag-ui/client=0.0.56
current @copilotkit/react-core=1.59.5
latest @copilotkit/react-core=1.59.5
current @copilotkit/runtime=1.59.5
latest @copilotkit/runtime=1.59.5
```

Решение: warning-only, зависимости не обновлялись.

## Проверки

Выполнено:

```bash
node --check static/src/ai_ui/native_ai.js
.venv/bin/python -m json.tool <workflow/json files>
git diff --check -- . ':(exclude)BACKLOG.md'
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
.venv/bin/python manage.py test apps.ai.tests
E2E_AI_UI_DRIVER=native E2E_USERNAME=native-e2e-user E2E_PASSWORD=native-e2e-pass E2E_BASE_URL=http://127.0.0.1:8001 npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
make gen-struct
```

Результаты:

- `apps.ai.tests`: 86 tests OK;
- `services.agent_runtime.tests.test_normalization`: 45 tests OK;
- native Playwright e2e: 2 tests passed.

## Остаточные риски

- `@ag-ui/client` latest `0.0.56` не внедрен. Нужно отдельное согласование.
- Production reverse proxy/SSE timeout для `native` нужно проверить на целевом хосте.
- Полная матрица `legacy`/`copilotkit`/`native` перед merge в `main` еще нужна как release smoke.
