# Workflow: версионируемая основа AI UI протоколов

## Цель

Подготовить общую основу для параллельной разработки CopilotKit/AG-UI и самописного AG-UI-compatible UI.

## Контекст

CopilotKit-пилот уже доказал рабочий путь через AG-UI, но часть общей логики пока живет в CopilotKit-specific местах. Перед разработкой второго варианта нужно отделить:

- actor/session context;
- подпись и TTL;
- UI driver selection;
- внутренние агентские события;
- AG-UI adapter;
- проектные расширения протокола;
- allow-list UI-команд.

## Read scope

- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- `apps/ai/`;
- `services/agent_runtime/`;
- `services/copilot_runtime/`;
- `templates/base.html`;
- `static/src/copilotkit/`;
- `scripts/e2e/tests/`.

## Write scope

Документационный этап:

- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/architecture/AI_UI_PROTOCOL_FOUNDATION_PLAN.md`;
- `docs/planning/archive/2026/ai-ui-protocol-foundation.md`;
- `workflow/archive/2026/ai-ui-protocol-foundation/`;
- `.desc.json`;
- `PROJECT_STRUCTURE.yaml`.

Будущий реализационный этап должен быть отдельным task packet и commit series.

## Non-goals

- Не менять production default UI.
- Не удалять legacy sidebar.
- Не включать hosted CopilotKit features.
- Не добавлять browser-side write tools.
- Не менять доменные tools/contracts без отдельного решения.

## Acceptance

- Есть ADR с решением по версионируемому протоколу.
- Есть архитектурный план.
- Есть активный planning-файл.
- Есть task packets для реализации.
- Документы явно разделяют общий слой, CopilotKit driver и native driver.
- Структура проекта обновлена.

## Verification

```bash
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```
