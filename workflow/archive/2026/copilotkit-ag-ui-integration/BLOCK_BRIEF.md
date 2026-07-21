# Workflow Brief: copilotkit-ag-ui-integration

Статус: proposed, documentation-ready.

Дата: 2026-06-09.

## Цель

Подготовить и затем реализовать безопасное пилотное встраивание CopilotKit в основной Django UI через AG-UI adapter, не заменяя текущий Django AI sidebar до приемки.

## Архитектурные источники

- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`
- `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`
- `docs/planning/archive/2026/copilotkit-ag-ui-integration.md`
- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`
- `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`
- `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`
- `docs/adr/ADR-0020-universal-right-drawer-ai-navigation.md`
- `docs/adr/ADR-0021-module-registered-agent-skills-and-mcp-facade.md`

## Read scope

- `apps/ai/`
- `apps/core/right_panels.py`
- `apps/core/ai_skills.py`
- `templates/ai/`
- `templates/core/`
- `static/src/js/ai_chat.js`
- `static/src/js/sidebar_chat.js`
- `static/src/js/page_context.js`
- `static/src/js/right_panel.js`
- `services/agent_runtime/`
- `contracts/ai/`
- `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`
- `docs/adr/ADR-0020-universal-right-drawer-ai-navigation.md`
- `docs/adr/ADR-0021-module-registered-agent-skills-and-mcp-facade.md`
- `docs/guides/AI_SIDEBAR_CHAT.md`
- `docs/guides/AI_SKILLS_OPERATIONS.md`
- `scripts/e2e/`

## Write scope

Ожидаемый write scope для будущей реализации:

- `services/agent_runtime/ag_ui_adapter.py`
- `services/agent_runtime/app.py`
- `services/agent_runtime/schemas.py`
- `services/agent_runtime/tests/`
- `services/agent_runtime/README.md`
- `services/copilot_runtime/`
- `templates/ai/`
- `static/src/` или выбранная frontend entrypoint-директория
- `scripts/e2e/tests/`
- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`
- `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`
- `.desc.json` files
- `PROJECT_STRUCTURE.yaml`

Root orchestration files, Docker Compose and `.env.example` менять только после явного согласования deployment-среза.

## Non-goals

- Не переписывать основной портал на React/Next.
- Не заменять текущий sidebar до приемки.
- Не переносить business tools из Django AI gateway.
- Не включать Copilot Cloud или hosted persistence.
- Не использовать browser direct `HttpAgent` в production.
- Не открывать write-действия через frontend tools.
- Не хранить raw prompts, PII, session cookies или secrets в AG-UI state.

## Ключевое решение

AG-UI является совместимым событийным протоколом agent runtime. CopilotKit является дополнительным UI-клиентом через server-side Copilot Runtime. Django остается владельцем данных, прав, истории и audit.

## Acceptance

- ADR-0027 принят или явно изменен.
- `/ag-ui` endpoint отдает валидный AG-UI stream.
- Старые `/chat` и `/chat/stream` не ломаются.
- Copilot Runtime подключается к `/ag-ui` server-side.
- React island включается feature flag'ом.
- Пользователь без доступа не может открыть или изменить чужой объект.
- Write tools сохраняют confirmation и audit.
- UI-команды ограничены allow-list.
- Telemetry выключена в on-prem profile.
- Deployment и operations docs обновлены.
- E2E покрывает основной сценарий CopilotKit panel.

## Verification

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm --prefix services/copilot_runtime test
npm --prefix services/copilot_runtime run typecheck
npm run test:e2e -- --project=chromium --grep "copilotkit|ag-ui|sidebar"
make gen-struct
git diff --check
```
