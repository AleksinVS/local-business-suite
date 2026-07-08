# Версионируемая основа AI UI протоколов

## Статус

Active implementation. Первый срез реализован в ветке `feature/copilotkit-ag-ui-integration`; требуется полная e2e-приемка на целевом окружении.

## Цель

Подготовить общий слой для параллельной разработки двух вариантов AI UI:

- самописный AG-UI-compatible UI как основной целевой ИИ-чат;
- CopilotKit/AG-UI как равноправный драйвер, пилот и референс совместимости.

Оба варианта должны использовать один backend-контур: actor/session context, page context, агентские события, UI-команды, права, confirmation flow и audit.

## Связанные документы

- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/architecture/AI_UI_PROTOCOL_FOUNDATION_PLAN.md`;
- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- `workflow/archive/2026/ai-ui-protocol-foundation/`.

## Пользовательская ценность

Владелец проекта сможет сравнить два AI UI варианта без расхождения backend-логики:

- готовый CopilotKit stack;
- контролируемый самописный UI.

Deployment сможет выбирать вариант через настройку, а не через разные ветки или ручные правки кода.

Основной долгосрочный пользовательский путь - самописный UI. CopilotKit полезен как быстрый production candidate, источник UX/runtime-паттернов и проверка AG-UI совместимости общего backend.

## Предлагаемый write scope

Документационный этап выполнен:

- `docs/adr/`;
- `docs/architecture/`;
- `docs/planning/active/`;
- `workflow/archive/2026/ai-ui-protocol-foundation/`;
- `.desc.json`;
- `PROJECT_STRUCTURE.yaml`.

Реализационный этап первого среза выполнен:

- `apps/ai/ui_runtime/`;
- `apps/ai/context_processors.py`;
- `apps/ai/views.py`;
- `apps/ai/urls.py`;
- `config/settings.py`;
- `templates/base.html`;
- `services/agent_runtime/protocols/`;
- `services/agent_runtime/app.py`;
- `services/agent_runtime/schemas.py`;
- `services/agent_runtime/tests/`;
- `static/src/ai_ui/` или отдельный native entrypoint;
- e2e tests.

## Non-goals

- Не удалять текущий HTMX sidebar.
- Не заменять CopilotKit-пилот до приемки.
- Не менять доменные AI tools.
- Не переносить write-действия в браузер.
- Не включать hosted CopilotKit services.
- Не менять contracts без отдельного scope.

## План работ

### 1. Общая документация и ADR

Статус: выполнено.

Результат:

- принято или уточнено ADR-0028;
- создан архитектурный план;
- создан workflow-блок.

### 2. Общий Django AI UI runtime

Статус: выполнено.

Вынести из CopilotKit-specific view:

- actor payload builder;
- signature payload;
- HMAC signer;
- config payload;
- выбор UI driver.

Целевая настройка:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy|copilotkit|native
```

### 3. Версионируемый protocol layer в agent runtime

Статус: выполнено.

Создать `services/agent_runtime/protocols/`:

- `common.events`;
- `common.capabilities`;
- `common.ui_commands`;
- `agui.v1`;
- опционально `native.v1`.

### 4. CopilotKit driver refactor

Статус: выполнено.

Перевести текущий CopilotKit path на общий runtime:

- сохранить `/ai/chat/copilotkit/config/` как совместимый endpoint или добавить нейтральный alias;
- сохранить `/copilotkit`;
- сохранить текущий e2e.

### 5. Native AG-UI-compatible UI

Статус: выполнено как минимальный sidebar driver.

Добавить самописный UI driver:

- отдельный frontend entrypoint;
- чтение AG-UI SSE;
- отрисовка сообщений, tool trace, ошибок;
- выполнение только allow-listed UI-команд.

### 6. Проверки, deployment, приемка

Статус: частично выполнено.

Обновить:

- deployment docs;
- operations docs;
- e2e matrix;
- rollback guide.

## Acceptance criteria

- Общие pieces не называются CopilotKit, если они используются обоими UI.
- AG-UI-compatible endpoint имеет protocol metadata.
- Самописный UI может использовать `/ag-ui` без Copilot Runtime.
- CopilotKit UI продолжает работать через Copilot Runtime.
- Старый HTMX sidebar остается fallback.
- Unknown extensions игнорируются клиентами.
- UI-команды версионированы и проходят allow-list.
- E2E покрывает минимум один сценарий для каждого драйвера.

## Реализованные файлы первого среза

- `apps/ai/ui_runtime/`;
- `services/agent_runtime/protocols/`;
- `static/src/ai_ui/`;
- `GET /ai/ui/config/`;
- `POST /ai/ui/ag-ui/run/`;
- `scripts/e2e/tests/native_ai_ui.spec.ts`.

## Риски

- AG-UI и CopilotKit быстро меняются. Нужно фиксировать версии пакетов, проверять актуальность версии при backend-изменениях и по умолчанию только предупреждать владельца, не обновляя зависимости без согласования.
- Дублирование UI-команд может вызвать рассинхронизацию. Нужен единый нормализатор.
- Native UI может начать повторять CopilotKit runtime behavior. Нужно держать его тонким клиентом AG-UI, пока нет доказанной потребности в отдельном backend protocol.
- Одновременная работа в двух больших ветках приведет к конфликтам. Общую основу лучше влить в `main` до активного native UI.

## Проверки

Документационный срез:

```bash
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```

После реализации:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
npm run test:e2e -- --project=chromium
```
