# CopilotKit и AG-UI: план интеграции в основной Django UI

## Статус

Accepted. В ветке добавлен первый рабочий срез: AG-UI endpoint, CopilotKit Runtime service, React-остров в основной Django-оболочке, feature flag и Playwright e2e для CopilotKit/fallback режимов.

Архитектурное решение: `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`.

Активный план: `docs/planning/archive/2026/copilotkit-ag-ui-integration.md`.

Workflow-блок: `workflow/archive/2026/copilotkit-ag-ui-integration/`.

## Методологическая заметка

Интеграция агентного UI состоит из трех независимых частей: протокол событий, runtime-прокси и визуальный компонент. Если смешать эти уровни, UI начинает обходить права и доменную логику. Поэтому AG-UI рассматривается как wire protocol, Copilot Runtime - как серверный прокси, а CopilotKit React UI - как заменяемый клиентский слой.

## Цель

Проверить, можно ли встроить CopilotKit в основной интерфейс портала без переписывания Django UI и без ослабления текущих гарантий:

- Django остается источником истины;
- бизнес-действия проходят через Django AI gateway;
- write tools требуют подтверждения там, где это требуется сейчас;
- audit/correlation identifiers сохраняются;
- memory search и page context не раскрывают лишние данные;
- текущий AI sidebar остается рабочим fallback.

## Текущее состояние

Сейчас поток выглядит так:

```text
templates/ai + static/src/js/ai_chat.js
  -> apps.ai.views.AIChatStreamView
  -> apps.ai.runtime_client.AgentRuntimeClient.chat_stream
  -> services.agent_runtime /chat/stream
  -> services.agent_runtime.graph.stream_agent
  -> DjangoGatewayClient.execute_tool
  -> apps.ai.views gateway tools
```

Потоковый ответ использует SSE, но события не являются AG-UI:

```text
data: {"content": "..."}
data: {"ui_command": {...}}
data: [DONE]
```

Целевой CopilotKit-путь требует AG-UI stream и discovery через Copilot Runtime.

## Целевая архитектура

```text
Browser / Django page
  |
  | static/dist/copilotkit/copilotkit-island.js
  v
React island
  |
  | <CopilotKit runtimeUrl="/copilotkit" agent="local_business">
  v
Copilot Runtime service
  |
  | HttpAgent -> AG-UI
  v
services.agent_runtime /ag-ui
  |
  | adapter
  v
existing LangGraph agent
  |
  | bounded tools
  v
Django AI gateway
  |
  v
domain services / policies / audit / memory
```

## Границы ответственности

### Django

- аутентификация и session ownership;
- выдача шаблонов и feature flags;
- история чата и `ChatSession`;
- `AIWindowContextSnapshot`;
- AI gateway;
- tool execution;
- confirmation flow;
- audit;
- runtime contracts.

### Agent runtime

- LangGraph orchestration;
- tool binding;
- skill activation;
- AG-UI event mapping;
- safe propagation of `conversation_id`, `request_id`, `origin_channel`;
- no direct Django ORM writes.

### Copilot Runtime

- runtime endpoint для CopilotKit provider;
- routing to AG-UI agent;
- server-side auth/header propagation;
- optional CopilotKit middleware;
- no business logic.

### React island

- visual AI panel;
- frontend-only UI tools;
- rendering tool activity;
- safe page context envelope;
- no direct domain writes.

## Этапы

### Этап 0. Документация и решение

Статус: подготовлено этой веткой.

Результаты:

- ADR-0027;
- архитектурный план;
- planning-файл;
- workflow-пакет;
- operations guide;
- deployment note.

### Этап 1. AG-UI adapter в agent runtime

Задачи:

- добавить endpoint `POST /ag-ui`;
- определить Pydantic-модель входа, совместимую с AG-UI `RunAgentInput`;
- написать mapper из текущего `stream_agent` в AG-UI events;
- выделить mapper в тестируемый модуль, например `services/agent_runtime/ag_ui_adapter.py`;
- не менять текущие `/chat` и `/chat/stream`;
- добавить unit tests на порядок событий и ошибки.

Минимальный event mapping:

```text
start request -> RUN_STARTED
first text chunk -> TEXT_MESSAGE_START
text chunk -> TEXT_MESSAGE_CONTENT
text complete -> TEXT_MESSAGE_END
tool trace item -> TOOL_CALL_START / TOOL_CALL_ARGS / TOOL_CALL_END / TOOL_CALL_RESULT
ui_command -> STATE_DELTA или CUSTOM_EVENT с allow-list
success -> RUN_FINISHED
error -> RUN_ERROR
```

Особое правило: в AG-UI stream нельзя отдавать raw tool payload, если он содержит PII, секреты, raw paths, actor context или полный prompt.

Статус первого среза: выполнено. `/ag-ui` принимает подписанный Django actor payload и не меняет `/chat` или `/chat/stream`.

### Этап 2. Copilot Runtime service

Задачи:

- добавить `services/copilot_runtime/`;
- поднять Node/HTTP endpoint `/copilotkit`;
- подключить AG-UI agent через server-side `HttpAgent`;
- прокидывать только разрешенные headers:
  - request id;
  - CSRF/session context через same-origin cookie или server-side token exchange;
  - feature flag context;
- отключить telemetry через env;
- добавить health endpoint;
- добавить README и smoke-команды.

Прямой browser `HttpAgent` допускается только в `.local/` spike или e2e-прототипе.

Статус первого среза: выполнено как `services/copilot_runtime/server.mjs`, Dockerfile и root npm script `copilot-runtime:start`. Отдельный `package.json` внутри сервиса не добавлен: зависимости закреплены в корневом lock-файле.

### Этап 3. React island в Django UI

Задачи:

- добавить отдельный frontend entrypoint;
- собрать bundle в штатную static-директорию;
- встроить контейнер в AI sidebar или отдельный маршрут;
- включать только по feature flag;
- сохранить fallback на текущий sidebar;
- передавать safe context через data-attributes или отдельный JSON endpoint;
- не читать DOM целиком.

Планируемый контейнер:

```html
<div
  id="copilotkit-sidebar-root"
  data-runtime-url="/copilotkit"
  data-agent-id="local_business"
  data-config-url="/ai/chat/copilotkit/config/"
></div>
```

Статус первого среза: выполнено как `static/src/copilotkit/main.jsx`, `vite.copilotkit.config.mjs` и контейнер `#copilotkit-sidebar-root` в `templates/base.html`.

### Этап 4. UI tools и human-in-the-loop

Задачи:

- перенести `ui.open_right_panel` на безопасный frontend handler только как UI-команду;
- оставить backend-проверку видимости объекта;
- описать renderers для tool activity;
- запретить frontend write tools;
- для write-action confirmations использовать существующий Django confirmation flow или отдельный backend tool result, но не browser-only approval.

### Этап 5. Проверки безопасности и приватности

Проверить:

- пользователь без прав не видит и не открывает чужие объекты;
- write tools не выполняются без confirmation;
- CopilotKit state не содержит raw PII, секреты, UNC paths, access tokens;
- telemetry выключена в on-prem profile;
- AG-UI errors не раскрывают stack trace;
- request ids попадают в audit.

### Этап 6. Deployment

Обновить:

- Docker Compose для Linux/VPS;
- IIS/Caddy reverse proxy notes;
- `.env.example`;
- health checks;
- rollback guide.

## Конфигурация

Предлагаемые переменные:

```text
LOCAL_BUSINESS_COPILOTKIT_ENABLED=false
LOCAL_BUSINESS_COPILOTKIT_RUNTIME_URL=/copilotkit
LOCAL_BUSINESS_COPILOTKIT_AGENT_ID=local_business
LOCAL_BUSINESS_COPILOTKIT_ACTOR_TOKEN_TTL_SECONDS=900
LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL=http://agent-runtime:8090/ag-ui
COPILOTKIT_BASE_PATH=/copilotkit
COPILOTKIT_RUNTIME_PORT=3100
COPILOTKIT_TELEMETRY_DISABLED=true
```

Дополнительные секреты для service-to-service auth должны храниться только в deployment-среде, не в Git.

## Проверки реализации

Минимальный набор:

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

Если добавлен `services/copilot_runtime`, дополнительно:

```bash
npm run copilot-runtime:start
curl -fsS http://127.0.0.1:3100/health
```

## Acceptance

- Текущий AI sidebar работает без CopilotKit.
- CopilotKit island включается только через feature flag.
- `/ag-ui` отдает валидный AG-UI event stream.
- Copilot Runtime подключается к `/ag-ui` server-side.
- `ui.open_right_panel` работает через безопасную команду и не обходит Django permissions.
- Write tools сохраняют confirmation и audit.
- История чата и audit остаются в Django.
- Документация deployment и operations обновлена.
- E2E покрывает первый безопасный сценарий: CopilotKit panel загружается, Django выдает подписанный actor config, Copilot Runtime и Agent Runtime отвечают health, `/ag-ui` принимает подписанный запрос, контекст открытой заявки обновляется в UI.
- Живой LLM/tool сценарий остается smoke-приемкой после настройки реального provider.

## Отложенные решения

- Нужен ли отдельный Settings Center переключатель для CopilotKit.
- Нужны ли CopilotKit generative UI renderers для карточек заявок или достаточно right drawer.
- Нужно ли подключать CopilotKit MCP apps к текущему MCP-фасаду.
- Нужна ли отдельная таблица для AG-UI run metadata.
- Будет ли CopilotKit использоваться в Tauri/PWA клиентах.
