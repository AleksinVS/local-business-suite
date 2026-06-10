# Workflow: разработка самописного AG-UI ИИ-чата

## Цель

Сделать самописный `native` ИИ-чат полноценным AG-UI-compatible клиентом и перенести в него полезные решения из CopilotKit-пилота без зависимости от Copilot Runtime.

## Контекст

ADR-0028 определяет самописный чат как основной целевой UI проекта. CopilotKit остается равноправным драйвером и референсом. Первый native-драйвер уже есть, но пока минимальный: нет нового чата, расширенного AG-UI reducer, полноценного tool trace и e2e для UI-команд.

## Read scope

- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/architecture/AI_UI_PROTOCOL_FOUNDATION_PLAN.md`;
- `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `apps/ai/`;
- `services/agent_runtime/protocols/`;
- `templates/base.html`;
- `static/src/ai_ui/`;
- `static/src/js/page_context.js`;
- `static/src/js/right_panel.js`;
- `scripts/e2e/tests/native_ai_ui.spec.ts`.

## Write scope

- `docs/architecture/NATIVE_AG_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/planning/active/native-ag-ui-chat-development.md`;
- `workflow/active/native-ag-ui-chat-development/`;
- `templates/base.html`;
- `apps/ai/context_processors.py`;
- `apps/ai/ui_runtime/config.py`;
- `static/src/ai_ui/native_ai.js`;
- `static/src/ai_ui/native_ai.css`;
- `scripts/e2e/tests/native_ai_ui.spec.ts`;
- `apps/ai/tests.py`;
- `docs/guides/AI_UI_PROTOCOL_OPERATIONS.md`;
- `.desc.json`;
- `PROJECT_STRUCTURE.yaml`.

## Non-goals

- Не обновлять AG-UI/CopilotKit зависимости.
- Не удалять CopilotKit и legacy драйверы.
- Не менять доменные tools/contracts.
- Не добавлять browser-side write actions.
- Не публиковать `agent_runtime` напрямую в браузер.

## Acceptance

- Native UI использует `/ai/ui/config/`.
- Новый чат создает новый `thread_id`.
- AG-UI text/tool/state/custom/error events обрабатываются без зависаний.
- UI-команды открывают правую панель через существующий safe bridge.
- Page context обновляется реактивно.
- E2E покрывает streaming, новый чат, tool trace и UI-команды.
- Документация и структура обновлены.

## Verification

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
node --check static/src/ai_ui/native_ai.js
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```

## AG-UI version note

Проверка 2026-06-10: текущий `@ag-ui/client=0.0.55`, latest npm `0.0.56`. Версия не обновляется без согласования владельца.
