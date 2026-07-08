# Executor report: implementation

## Scope

Реализован первый срез общей версионируемой основы AI UI протоколов.

## Изменения

- Добавлен `apps.ai.ui_runtime`:
  - `drivers.py`;
  - `actor.py`;
  - `config.py`.
- Добавлена настройка `LOCAL_BUSINESS_AI_UI_DRIVER=legacy|copilotkit|native`.
- Добавлены `LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION`, `LOCAL_BUSINESS_AI_UI_AGUI_PROFILE`, `LOCAL_BUSINESS_AI_UI_ACTOR_TOKEN_TTL_SECONDS`.
- Добавлены `GET /ai/ui/config/` и `POST /ai/ui/ag-ui/run/`.
- Native proxy пересоздает actor payload на сервере и не доверяет клиентскому actor.
- Добавлен `services.agent_runtime.protocols`:
  - common capabilities;
  - common UI command allow-list;
  - AG-UI events;
  - AG-UI v1 mapper.
- `/ag-ui` отдает `local_business.protocol` metadata event.
- `open_right_panel` получил `version` и новый state path `/localBusiness/uiCommands`.
- Старый path `/localBusinessUiCommands` оставлен для CopilotKit compatibility.
- CopilotKit config и React island переведены на общий слой.
- Добавлен native sidebar `static/src/ai_ui/native_ai.js`.
- Добавлен Playwright spec `native_ai_ui.spec.ts`.

## Проверки

Выполнено:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python manage.py test apps.ai.tests.AIViewsTests.test_copilotkit_config_is_feature_flagged apps.ai.tests.AIViewsTests.test_copilotkit_config_returns_signed_actor_payload apps.ai.tests.AIViewsTests.test_native_ai_ui_config_returns_signed_actor_payload apps.ai.tests.AIViewsTests.test_native_ai_ui_proxy_overwrites_client_actor_payload
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization.TestAGUIAdapter services.agent_runtime.tests.test_normalization.TestAGUIRuntimeEndpoint -v
node --check static/src/ai_ui/native_ai.js
node --check services/copilot_runtime/server.mjs
npm run build:copilotkit
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit AG-UI sidebar"
E2E_AI_UI_DRIVER=legacy npm run test:e2e -- --project=chromium --grep "context-aware sidebar AI chat"
```

## Остаточные риски

- Native UI пока минимальный и не восстанавливает историю после перезагрузки страницы.
- Production-включение требует проверки reverse proxy и timeout на целевом хосте.
- Независимый read-only субагент был запущен для дополнительной проверки, но не вернул отчет до закрытия; итоговая приемка опирается на локальные проверки выше.
