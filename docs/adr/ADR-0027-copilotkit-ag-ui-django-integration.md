# ADR-0027: CopilotKit и AG-UI как дополнительный интерфейс ИИ-чата

## Статус

Accepted

## Дата

2026-06-09

## Контекст

Проект уже имеет рабочий контур ИИ-чата:

```text
браузер
  -> Django views/templates/HTMX/custom JS
  -> services.agent_runtime FastAPI/LangGraph
  -> Django AI gateway
  -> доменные services, policies, confirmation и audit
```

Текущий streaming работает через SSE, но формат событий проектный: `content`, `ui_command`, `[DONE]`.

CopilotKit дает готовый слой пользовательского интерфейса для агентных приложений, а AG-UI задает стандартный событийный протокол между агентом и UI. По официальной документации CopilotKit built on AG-UI: сообщения, state updates и tool calls идут через AG-UI events поверх Server-Sent Events. Production-путь CopilotKit предполагает Copilot Runtime, а прямое подключение `HttpAgent` к агенту предназначено для разработки и прототипов, не для production.

Полезные источники:

- https://github.com/CopilotKit/CopilotKit
- https://docs.copilotkit.ai/backend/ag-ui
- https://docs.copilotkit.ai/google-adk/backend/copilot-runtime
- https://docs.ag-ui.com/concepts/events
- https://docs.copilotkit.ai/built-in-agent/telemetry

## Решение

Принять CopilotKit как **дополнительный UI-слой**, а AG-UI как **совместимый протокол событий** для будущего пилота. Не заменять текущий Django/HTMX AI sidebar в первом срезе.

Целевой путь:

```text
Django template
  -> React island с CopilotKit UI
  -> Copilot Runtime как отдельный Node/HTTP service
  -> AG-UI endpoint в services.agent_runtime
  -> существующий LangGraph agent
  -> Django AI gateway
  -> policies, confirmation, audit, memory
```

### Django остается источником истины

Сессии, права, история чата, audit, подтверждения write-действий, memory policies и доменные операции остаются в Django. CopilotKit не получает прямой доступ к Django ORM, runtime contracts или data-директориям.

### AG-UI adapter добавляется в agent runtime

В `services/agent_runtime` допускается добавить отдельный endpoint, например `/ag-ui`, который переводит текущий agent stream в AG-UI events:

- `RUN_STARTED`;
- `TEXT_MESSAGE_START`;
- `TEXT_MESSAGE_CONTENT`;
- `TEXT_MESSAGE_END`;
- `TOOL_CALL_START`;
- `TOOL_CALL_ARGS`;
- `TOOL_CALL_END`;
- `TOOL_CALL_RESULT`;
- `STATE_DELTA` для безопасных UI-команд;
- `RUN_FINISHED`;
- `RUN_ERROR`.

Существующие `/chat` и `/chat/stream` сохраняются для основного Django sidebar до отдельной приемки.

### Copilot Runtime выносится в отдельный service

Если пилот идет дальше прототипа, добавить отдельный сервис:

```text
services/copilot_runtime/
  Dockerfile
  server.mjs
```

Этот сервис отвечает только за Copilot Runtime endpoint и проксирование AG-UI agent. Он не выполняет бизнес-логику и не пишет в базу.

Для первого среза Node-зависимости закреплены в корневых `package.json` и `package-lock.json`, а сервис запускается командой `npm run copilot-runtime:start`.

Прямое подключение CopilotKit frontend к `HttpAgent` разрешено только для локального прототипа и e2e-spike. В production использовать `runtimeUrl` и серверный Copilot Runtime.

### React island, а не переписывание портала

В основной Django UI CopilotKit встраивается как изолированный React island внутри существующего шаблона, например в левую AI-панель или отдельный экспериментальный маршрут. Feature flag обязателен:

```text
LOCAL_BUSINESS_COPILOTKIT_ENABLED=false
```

До приемки пилота текущий AI sidebar остается основным.

Контекст исполнителя передается из Django в CopilotKit как подписанный HMAC payload с коротким TTL. Agent runtime отклоняет AG-UI запросы без действующей подписи до вызова агента.

### Frontend tools только для UI-действий

Разрешенный класс browser-side действий:

- открыть правый сайдбар;
- прокрутить список;
- выбрать вкладку;
- показать безопасное состояние UI.

Запрещено:

- менять доменные данные из frontend tool напрямую;
- обходить Django AI gateway;
- передавать raw PII, секреты, UNC paths или полный page DOM в state;
- хранить источник истины чата в CopilotKit persistence вместо Django.

Write-действия остаются только backend tools через Django gateway, confirmation flow и audit.

### Privacy и telemetry

Для on-prem/medical context по умолчанию:

```text
COPILOTKIT_TELEMETRY_DISABLED=true
```

Copilot Cloud, hosted persistence, внешняя аналитика CopilotKit и in-context reinforcement learning не включаются без отдельного privacy/security review и нового ADR.

## Альтернативы

### Ничего не менять

Плюсы:

- минимальный риск;
- текущий Django UI остается простым для сопровождения.

Минусы:

- проектный SSE-протокол остается закрытым;
- сложнее подключать готовые агентные UI-компоненты и сторонние клиенты.

### Полностью заменить текущий AI sidebar на CopilotKit

Отклонено для первого этапа. Это увеличивает фронтенд-стек, затрагивает рабочий сценарий пользователей и может нарушить текущие page context, audit и confirmation flows.

### Прямой `HttpAgent` из браузера в agent runtime

Разрешено только для локального прототипа. Для production отклонено: авторизация, middleware, routing, observability и security defaults должны жить на серверном runtime-слое.

### Перенести agent orchestration в CopilotKit Built-in Agent

Отклонено. В проекте уже есть self-hosted LangGraph runtime, MCP-фасад, module skills и Django AI gateway. Перенос orchestration не дает достаточной выгоды и повышает риск нарушения доменных границ.

## Последствия

Положительные:

- появляется стандартный AG-UI слой без отказа от Django-first архитектуры;
- можно пилотировать CopilotKit UI изолированно;
- будущие клиенты смогут использовать тот же agent backend;
- сохраняются текущие права, подтверждения, audit и memory policies.

Отрицательные:

- появляется новый JavaScript runtime-сервис;
- нужно поддерживать сборку React island;
- нужно добавить e2e и security-проверки событий AG-UI;
- deployment для Linux и Windows/IIS усложняется.

## Требования к реализации

- Все новые временные артефакты писать в `.local/`.
- При добавлении `services/copilot_runtime/` обновить `.desc.json` и `PROJECT_STRUCTURE.yaml`.
- Добавить unit tests для AG-UI event mapper.
- Добавить integration/e2e для CopilotKit island за feature flag.
- Проверить, что пользователь без прав не может выполнить write-action через CopilotKit.
- Проверить, что `ui.open_right_panel` продолжает проходить через безопасную команду, а не через прямой DOM/URL bypass.
- Обновить deployment docs и smoke-команды.
