# Workflow: разработка ИИ-чата в режиме CopilotKit UI

## Цель

Довести ИИ-чат в режиме `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit` до production candidate в основном Django UI.

## Контекст

Ветка уже содержит первый рабочий срез CopilotKit/AG-UI и общий слой AI UI protocol foundation. Следующий срез должен превратить пилот в проверяемый продуктовый чат:

- новый чат и разделение сессий;
- потоковый ответ;
- безопасный контекст страницы;
- tool trace без лишних данных;
- UI-команды через allow-list;
- понятные ошибки;
- e2e и deployment-приемка.

## Read scope

- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`;
- `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`;
- `apps/ai/`;
- `services/agent_runtime/`;
- `services/copilot_runtime/`;
- `static/src/copilotkit/`;
- `templates/base.html`;
- `scripts/e2e/tests/`.

## Write scope

Документационный срез:

- `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/planning/archive/2026/copilotkit-ai-ui-chat-development.md`;
- `workflow/archive/2026/copilotkit-ai-ui-chat-development/`;
- `.desc.json`;
- `PROJECT_STRUCTURE.yaml`;
- `docs/planning/backlog.md`.

Реализационный срез:

- `apps/ai/ui_runtime/`;
- `apps/ai/views.py`;
- `apps/ai/urls.py`;
- `services/agent_runtime/protocols/`;
- `services/agent_runtime/app.py`;
- `services/copilot_runtime/`;
- `static/src/copilotkit/`;
- `templates/base.html`;
- `scripts/e2e/tests/`;
- docs/guides/deployment по факту изменения запуска.

## Non-goals

- Не удалять `legacy` driver.
- Не реализовывать самописный UI в этом workflow-блоке.
- Не переносить domain writes в браузер.
- Не включать hosted CopilotKit persistence.
- Не менять domain tools/contracts без отдельного task packet.

## Acceptance

- CopilotKit-чат включается через `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit`.
- Новый чат отвечает в новой Django chat session.
- Контекст страницы применяется безопасно.
- `ui.open_right_panel` работает через версионированную UI-команду.
- Ошибки Copilot Runtime, Agent Runtime и LLM отображаются корректно.
- Секреты и sensitive payload не попадают в browser state.
- История и audit остаются в Django.
- Rollback на `legacy` проверен.
- E2E `--grep "CopilotKit"` проходит.

## Verification

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
E2E_AI_UI_DRIVER=copilotkit npm run test:e2e -- --project=chromium --grep "CopilotKit"
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```
