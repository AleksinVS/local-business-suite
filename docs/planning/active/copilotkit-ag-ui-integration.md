# CopilotKit и AG-UI в основном Django UI

## Статус

Active implementation. Документация, первый рабочий срез реализации и локальный Playwright e2e добавлены в отдельной ветке.

Архитектурное решение: `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`.

Проектный план: `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`.

Операционные документы:

- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md`;
- `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`.

Workflow-блок: `workflow/active/copilotkit-ag-ui-integration/`.

## Цель

Пилотно встроить CopilotKit в основной Django UI как изолированный React island поверх стандартного AG-UI stream, сохранив текущий Django/HTMX AI sidebar как fallback.

## Пользовательская ценность

- Более современный чат-интерфейс с видимостью tool activity.
- Возможность будущего generative UI без переписывания доменной логики.
- Единый agent backend для Django UI и потенциальных внешних клиентов.
- Меньше проектной привязки к собственному SSE-формату.

## Принципы

1. Django остается источником истины.
2. AG-UI добавляется как совместимый протокол, а не как новая доменная модель.
3. CopilotKit встраивается только как React island.
4. Production-путь идет через Copilot Runtime, не через прямой browser `HttpAgent`.
5. Текущий AI sidebar сохраняется до приемки.
6. Все write-действия проходят через Django AI gateway, confirmation и audit.
7. Frontend tools могут выполнять только UI-действия.
8. Copilot Cloud и внешняя persistence не включаются без отдельного review.
9. Telemetry выключается по умолчанию для on-prem profile.

## Не цели

- Не переписывать весь портал на React/Next.
- Не переносить LangGraph orchestration в CopilotKit Built-in Agent.
- Не переносить историю чата из Django.
- Не открывать Django AI gateway браузеру напрямую.
- Не включать hosted CopilotKit services.
- Не менять contracts/ai tools без отдельного write scope.

## Этапы

### Этап 0. Документация и приемка подхода

Результат этой ветки:

- ADR;
- проектный план;
- operations/deployment docs;
- workflow package.

Статус: выполнено.

### Этап 1. AG-UI adapter

Write scope:

- `services/agent_runtime/ag_ui_adapter.py`;
- `services/agent_runtime/app.py`;
- `services/agent_runtime/schemas.py`;
- `services/agent_runtime/tests/`;
- `services/agent_runtime/README.md`.

Acceptance:

- `/ag-ui` не ломает `/chat/stream`;
- event order покрыт тестами;
- ошибки маппятся в безопасный `RUN_ERROR`;
- `ui_command` не раскрывает raw payload.

Статус: выполнено в первом срезе. Дополнительно добавлена проверка HMAC-подписи actor payload.

### Этап 2. Copilot Runtime service

Write scope:

- `services/copilot_runtime/`;
- `services/.desc.json`, если есть;
- deployment docs;
- root orchestration files only after explicit approval.

Acceptance:

- сервис имеет health endpoint;
- использует server-side `HttpAgent`;
- отключает telemetry;
- не имеет доступа к БД;
- умеет прокинуть request/session context безопасно.

Статус: выполнено как root npm-зависимости + `services/copilot_runtime/server.mjs`.

### Этап 3. React island

Write scope:

- frontend entrypoint;
- static bundle configuration;
- templates AI sidebar или отдельный experimental route;
- e2e tests.

Acceptance:

- включается feature flag;
- текущий sidebar остается fallback;
- visual state не ломает mobile/desktop layout;
- frontend tools выполняют только UI-команды.

Статус: выполнено как встроенный `CopilotChat` в левую AI-панель за feature flag.

### Этап 4. Security, e2e и deployment

Acceptance:

- user without permission cannot read/write hidden objects;
- write tools still require confirmation;
- audit trace contains request ids;
- docs and `.desc.json` updated;
- `make gen-struct` выполнен.

Статус: локальный e2e выполнен в двух режимах:

- `LOCAL_BUSINESS_COPILOTKIT_ENABLED=true`, `E2E_COPILOTKIT_ENABLED=true`: CopilotKit panel, signed actor config, Copilot Runtime health, Agent Runtime `/ag-ui` signed request and workorder context path;
- `LOCAL_BUSINESS_COPILOTKIT_ENABLED=false`: fallback HTMX sidebar scenarios.

Целевой reverse proxy `/copilotkit` и реальный LLM/provider остаются частью pilot-приемки на deployment.

## Проверки

Плановый минимум:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
E2E_COPILOTKIT_ENABLED=true npm run test:e2e -- --project=chromium
npm run test:e2e -- --project=chromium
make gen-struct
```

## Риски

- новый Node runtime усложняет deployment;
- AG-UI state может раскрыть лишний контекст при плохом mapper;
- CopilotKit UI может конфликтовать с текущей левой панелью;
- прямой `HttpAgent` в browser опасен для production;
- устаревание API CopilotKit/AG-UI требует pinning версий.

## Оставшаяся приемка

- проверить same-origin reverse proxy `/copilotkit` на целевом deployment;
- подтвердить `COPILOTKIT_TELEMETRY_DISABLED=true` в deployment-среде;
- выполнить приемку владельцем перед архивированием planning/workflow.
