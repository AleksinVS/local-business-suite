# Task acceptance: implementation

## Решение

Первый реализационный срез native AG-UI чата принят технически.

## Проверено

- Native sidebar использует `/ai/ui/config/`.
- Новый чат создает новый thread и обновляет config.
- AG-UI stream собирает assistant message из `TEXT_MESSAGE_*`.
- Tool trace отображается по `TOOL_CALL_*`.
- UI-команда из `STATE_DELTA /localBusiness/uiCommands` открывает правую панель один раз.
- `RUN_ERROR` показывает ошибку и разблокирует форму.
- Django proxy сохраняет user/assistant/error messages в `ChatSession`.
- Django proxy передает bound page context и trace context в runtime.

## Команды

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
node --check static/src/ai_ui/native_ai.js
E2E_AI_UI_DRIVER=native E2E_USERNAME=native-e2e-user E2E_PASSWORD=native-e2e-pass E2E_BASE_URL=http://127.0.0.1:8001 npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```

## Ограничения

- AG-UI dependency update не выполнялся.
- Production smoke на целевом reverse proxy остается перед включением пользователям.
