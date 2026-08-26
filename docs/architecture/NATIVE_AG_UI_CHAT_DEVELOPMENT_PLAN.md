# План разработки самописного AG-UI ИИ-чата

## Статус

Технически выполнено 2026-08-26. Документ фиксирует реализованный единый
native-контур и остаётся активным до пользовательской приёмки и production smoke.

Дата: 2026-06-10. Актуализировано: 2026-08-26.

Целевой режим:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=native
```

С 2026-06-15 это также режим по умолчанию при отсутствии `LOCAL_BUSINESS_AI_UI_DRIVER`; явная переменная нужна только для читаемости deployment-профиля.

## Связанные решения и документы

- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/adr/ADR-0044-unified-native-ai-chat-execution.md`;
- `docs/architecture/AI_UI_PROTOCOL_FOUNDATION_PLAN.md`;
- `docs/architecture/COPILOTKIT_AI_UI_CHAT_DEVELOPMENT_PLAN.md`;
- `docs/guides/AI_UI_PROTOCOL_OPERATIONS.md`;
- `docs/deployment/AI_UI_PROTOCOL_DEPLOYMENT.md`;
- `workflow/active/native-ag-ui-chat-development/`.

ADR-0044 уточняет ADR-0028: боковой и полноэкранный native-интерфейсы
используют один session-aware prepare/run путь; CopilotKit остается отдельным
эталонным клиентом общего runtime `/ag-ui`.

## Методологическая заметка

AG-UI в этом проекте является внешним wire contract между серверным агентом и UI. Поэтому самописный чат не должен копировать CopilotKit как библиотеку. Он должен повторить полезные пользовательские и runtime-паттерны: жизненный цикл run/thread, потоковую сборку сообщений, tool trace, state delta, обработку ошибок и безопасный page context.

## Проверка версии AG-UI

Текущие закрепленные версии:

```text
@ag-ui/client=0.0.55
@copilotkit/react-core=1.59.5
@copilotkit/runtime=1.59.5
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE=ag-ui@0.0.55
```

Проверка официальных источников 2026-08-26 показала:

```text
@ag-ui/client latest=0.0.58
@copilotkit/react-core latest=1.69.2
@copilotkit/runtime latest=1.69.0
```

Версия AG-UI не обновляется в этом срезе. Это осознанное предупреждение: требуется отдельное согласование владельца, оценка release notes и e2e matrix перед повышением `agui_profile`.

## Цель

Сделать самописный ИИ-чат основным AG-UI-compatible клиентом проекта без зависимости от Copilot Runtime.

Целевые свойства:

- корректный mount native root и загрузка `/ai/ui/config/`;
- новый чат через `POST /ai/ui/session/new/`;
- устойчивый AG-UI SSE parser;
- message reducer для `TEXT_MESSAGE_*`;
- tool trace reducer для `TOOL_CALL_*`;
- обработка `CUSTOM local_business.protocol`;
- выполнение `STATE_DELTA /localBusiness/uiCommands` и `CUSTOM local_business.ui_command`;
- реактивная передача page context;
- понятные ошибки для `RUN_ERROR`, HTTP/runtime сбоя и пустого stream;
- e2e, покрывающий streaming, новый чат, tool trace и UI-команды.

## Фактическая реализация первого среза

Выполнено:

- native sidebar подключается к `/ai/ui/config/`;
- native static assets подключаются с version query string;
- service worker пропускает `/static/src/ai_ui/` без cache-first обработки;
- native UI получил кнопку нового чата и обновление thread/config без перезагрузки;
- добавлен AG-UI SSE parser с обработкой lifecycle/text/tool/state/custom/error events;
- добавлен compact tool trace без raw tool payload;
- `STATE_DELTA /localBusiness/uiCommands` и `CUSTOM local_business.ui_command` выполняются через существующий safe right panel bridge;
- browser page context передается перед каждым run;
- Django proxy сохраняет user/assistant/error messages в `ChatSession`;
- Django proxy подмешивает историю из `ChatSession` в AG-UI request;
- добавлены unit и Playwright e2e проверки native-сценария.

## Non-goals

- Не обновлять AG-UI/CopilotKit версии.
- Не добавлять React/Vue или новый frontend framework.
- Не переносить доменные write tools в браузер.
- Не удалять CopilotKit-драйвер.
- Не менять схемы бизнес-контрактов.

## Архитектурный контур

```text
Browser native sidebar | full page
  -> session-aware config
  -> multipart prepare turn
  -> idempotent session run
  -> services.agent_runtime /ag-ui
  -> protocols.agui.v1
  -> LangGraph agent
  -> Django AI gateway
```

Владение:

- Django UI runtime: driver selection, actor/session payload, signature, config.
- Native frontend: AG-UI stream parsing, local message/tool UI state, safe UI commands.
- Django proxy: same-origin auth, ownership, prepared turns, replay protection,
  actor payload overwrite and AG-UI stream relay.
- Agent runtime: AG-UI event contract, protocol metadata, redaction, UI command normalization.

## Реализационный срез

### 1. Mount и config

Исправить `templates/base.html`, чтобы `native` branch использовал:

```text
#native-ai-sidebar-root
GET /ai/ui/config/
POST /ai/ui/session/new/
```

Native UI не должен использовать CopilotKit config endpoint.

### 2. Thread/run lifecycle

Реализовано в native UI:

- кнопку нового чата;
- обновление `thread_id` и адресов prepare/run после `POST /ai/ui/session/new/`;
- `runId` формата `native_<timestamp>_<random>`;
- блокировку формы только на время текущего run;
- серверное построение истории; состояние браузера не является источником
  контекста модели.

### 3. AG-UI stream parser и reducers

Native UI должен корректно обрабатывать:

- lifecycle: `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`;
- text: `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`;
- tools: `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, `TOOL_CALL_RESULT`;
- state: `STATE_SNAPSHOT`, `STATE_DELTA`;
- custom: `local_business.protocol`, `local_business.ui_command`;
- неизвестные события без падения.

### 4. Tool trace

Показывать compact trace:

- название tool;
- статус `выполняется`, `аргументы`, `готово`, `результат`;
- без raw sensitive payload;
- без доменных write-действий в браузере.

### 5. UI-команды и page context

Использовать только allow-listed `open_right_panel`:

- выполнять команды из `/localBusiness/uiCommands`;
- временно читать `/localBusinessUiCommands` для совместимости;
- дедуплицировать команды;
- после открытия правой панели обновлять page context через существующий мост.

Native UI должен слушать `ai-context:update` и брать свежий envelope перед каждым run.

### 6. Ошибки

Показывать понятное состояние:

- `RUN_ERROR`: текст из события или общий текст;
- HTTP error: "ИИ-сервис недоступен";
- empty stream: "ИИ-сервис не вернул ответ";
- network abort/runtime error: общий безопасный текст.

Технические коды остаются в event/logs, но не раскрывают stack trace.

## Acceptance criteria

- В режиме `LOCAL_BUSINESS_AI_UI_DRIVER=native` sidebar использует `/ai/ui/config/`, а не CopilotKit config.
- Пользователь может создать новый чат без перезагрузки страницы.
- AG-UI stream собирает assistant message из `TEXT_MESSAGE_*`.
- Tool trace отображается по `TOOL_CALL_*`.
- UI-команда из `STATE_DELTA /localBusiness/uiCommands` открывает правую панель один раз.
- `RUN_ERROR` не оставляет чат в бесконечной загрузке.
- Unknown event/custom extension не ломает UI.
- CopilotKit reference-драйвер не меняет архитектуру; legacy-драйвер ранее
  удалён по ADR-0032.
- E2E покрывает основной native сценарий.

## UX parity со старым чатом

Цель - сделать `native` не только технически AG-UI-compatible, но и функционально сопоставимым со старым Django/HTMX чатом.

### Baseline старого sidebar

Статус: выполнено в task packet `05-sidebar-history-model-and-clear-parity`.

Native sidebar получил:

- загрузку последних сообщений активной sidebar-сессии при открытии страницы;
- выбор модели из `LOCAL_BUSINESS_AI_MODELS`;
- очистку текущего sidebar-чата с подтверждением;
- timestamps у сообщений;
- ссылку или кнопку открытия полного чата текущей сессии;
- сохранение текущих гарантий page context, audit, actor signing и safe UI commands.

### Единый путь и полноэкранное представление

Статус: выполнено в task packets `06`, `07`, `08`.

Общий контур получил:

- строгую проверку владельца активной сессии и совпадения `threadId`;
- уникальный `(session, run_id)` и воспроизведение сохраненного результата;
- серверную подготовку пользовательского хода, команд, контекста и вложений;
- общий decoder/reducer, для которого EOF без terminal event является ошибкой;
- канонический поток `/ag-ui` без отдельного `/chat/stream`.

Native full-page chat получил:

- список последних `ChatSession` текущего пользователя;
- создание новой сессии;
- открытие существующей сессии без смешивания thread/history;
- переименование и удаление чата;
- безопасное Markdown-отображение ответов;
- меню и autocomplete slash-команд;
- вложения через существующий `ChatAttachment` контур;
- e2e на конфигурацию и сессии, безопасный поток, команды, вложения, Markdown и
  разблокировку после ошибки.

### Исполнительные task packets

```text
workflow/active/native-ag-ui-chat-development/task-packets/
  05-sidebar-history-model-and-clear-parity.json
  06-native-full-page-session-management.json
  07-native-rich-input-markdown-commands-attachments.json
  08-native-ux-parity-e2e-acceptance.json
```

### Ограничения

- Не обновлять AG-UI/CopilotKit версии без согласования владельца.
- Не добавлять browser-side write tools.
- Не создавать параллельное хранилище истории, команд или вложений.
- Не менять CopilotKit reference-путь и версии без отдельного решения.
- Старые native execution endpoints удалены после проверки отсутствия вызовов;
  откат не выполняется простым возвратом предыдущей Git-версии: старая схема и
  старый код не сохраняют данные и совместимость `ChatRun`. Нужен
  forward-compatible rollback либо backup/restore с явным планом миграции.
- Не тянуть CopilotKit Runtime в production-путь `native`.

## Проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.ai.tests
.venv/bin/python -m unittest services.agent_runtime.tests.test_normalization -v
node --check static/src/ai_ui/native_ai.js
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native AG-UI-compatible"
E2E_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "native chat UX parity"
make gen-struct
git diff --check -- . ':(exclude)BACKLOG.md'
```

## Риски

- `@ag-ui/client` уже имеет новую версию `0.0.58`, а CopilotKit — ветку
  `1.69.x`. В этом срезе риск принят как предупреждение без обновления.
- Native UI может начать дублировать Copilot Runtime. Смягчение: оставить его тонким AG-UI клиентом.
- Browser state может раскрыть лишнее. Смягчение: использовать существующий sanitized page context и server-side redaction.
- PWA cache может удерживать старый JS. Смягчение: добавить version query для native asset.
