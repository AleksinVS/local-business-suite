# Версионируемая основа AI UI протоколов

## Статус

Accepted. Первый реализационный срез выполнен: общий Django UI runtime, agent runtime protocol layer, protocol metadata, CopilotKit refactor и минимальный native AG-UI-compatible sidebar.

Связанные документы:

- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- `docs/planning/active/ai-ui-protocol-foundation.md`;
- `workflow/active/ai-ui-protocol-foundation/`.

## Методологическая заметка

Протокол интерфейса - это контракт между backend и UI. Если UI-библиотека становится этим контрактом напрямую, любая смена UI тянет за собой backend. Поэтому проекту нужен внутренний стабильный слой событий и отдельные адаптеры: один для CopilotKit/AG-UI, второй для самописного AG-UI-compatible UI. Основной продуктовый чат должен быть самописным, но по серверному контракту он остается таким же AG-UI клиентом, как CopilotKit.

## Цель

Сделать так, чтобы основной самописный AI UI и CopilotKit/AG-UI развивались параллельно поверх общей основы:

- один actor/session context;
- один набор безопасных UI-команд;
- один внутренний поток агентских событий;
- один AG-UI-compatible wire contract;
- версионируемые проектные расширения;
- выбор UI-варианта через настройки deployment.

## Продуктовый приоритет

Основной целевой вариант для проекта - самописный ИИ-чат в режиме `LOCAL_BUSINESS_AI_UI_DRIVER=native`. Он должен быть равноправным AG-UI клиентом, а не отдельным протоколом поверх тех же tools. Это означает:

- backend не должен знать, какой UI клиент подключен, кроме поля `driver` в metadata и config;
- CopilotKit и native получают один набор событий, UI-команд, прав, audit и истории;
- расширения проекта добавляются через `local_business_protocol`, `CUSTOM` и `STATE_DELTA`, а не через CopilotKit-specific payload;
- CopilotKit используется как рабочий эталон поведения, regression target и источник UX/runtime-паттернов.

## Non-goals

- Не переписывать агентскую orchestration.
- Не переносить бизнес-логику в Copilot Runtime или frontend.
- Не удалять текущий HTMX sidebar до приемки.
- Не включать Copilot Cloud, hosted persistence или внешнюю аналитику.
- Не добавлять browser-side write tools.

## Фактическое состояние первого среза

Реализовано:

- `apps/ai/ui_runtime/` для выбора драйвера, actor payload, подписи и config payload;
- `LOCAL_BUSINESS_AI_UI_DRIVER=legacy|copilotkit|native`, где по умолчанию без переменной окружения активен `native`;
- `GET /ai/ui/config/` для активного AI UI драйвера;
- `POST /ai/ui/ag-ui/run/` как Django same-origin proxy для native UI;
- `services/agent_runtime/protocols/common/` с capabilities и UI command allow-list;
- `services/agent_runtime/protocols/agui/` с AG-UI events и v1 mapper;
- `CUSTOM name="local_business.protocol"` в начале успешного `/ag-ui` run;
- `STATE_DELTA path="/localBusiness/uiCommands"` как основной путь UI-команд;
- временный compatibility path `/localBusinessUiCommands`;
- native sidebar `static/src/ai_ui/native_ai.js`;
- Playwright spec `scripts/e2e/tests/native_ai_ui.spec.ts`.

Оставшиеся ограничения:

- native UI пока минимальный: текст, tool trace и UI commands без расширенного UX истории;
- persistent chat history для native идет через agent runtime/Django контур, но UI после перезагрузки не восстанавливает прошлые сообщения;
- `services/agent_runtime/ag_ui_adapter.py` оставлен как compatibility re-export;
- отдельный `protocols.native.v1` не добавлен, потому что native UI пока использует AG-UI-compatible endpoint напрямую.

## Целевая архитектура

```text
Django template/base UI
  |
  | AI UI driver selector
  v
apps.ai.ui_runtime
  | actor config, signed context, page context, UI command contract
  |
  +--> legacy HTMX sidebar
  +--> copilotkit React island -> Copilot Runtime
  +--> native AG-UI UI -> Django same-origin AG-UI proxy

Copilot Runtime или native клиент
  |
  | AG-UI-compatible RunAgentInput
  v
services.agent_runtime /ag-ui
  |
  | protocols.agui.v1
  v
protocols.common.InternalAgentEvent stream
  |
  v
existing LangGraph agent -> Django AI gateway -> domain services
```

## Предлагаемая структура модулей

### Django-side общий слой

```text
apps/ai/ui_runtime/
  __init__.py
  actor.py
  config.py
  drivers.py
```

Назначение:

- создать actor payload;
- подписать actor payload;
- проверять допустимые UI-драйверы;
- выдавать безопасную конфигурацию клиенту;
- описывать allow-list UI-команд;
- не зависеть от CopilotKit.

### Agent runtime protocol layer

```text
services/agent_runtime/protocols/
  __init__.py
  common/
    __init__.py
    capabilities.py
    ui_commands.py
  agui/
    __init__.py
    events.py
    v1.py
```

Назначение:

- нормализовать входной запрос;
- проверить подпись actor payload;
- перевести внутренние события в AG-UI;
- добавить project extensions без нарушения AG-UI-compatible клиентов.

## UI-драйверы

Целевая настройка:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy|copilotkit|native
```

Если настройка отсутствует, Django выбирает `native`. Старый HTMX sidebar остается доступен через явное `LOCAL_BUSINESS_AI_UI_DRIVER=legacy`.

### `legacy`

Текущий Django/HTMX sidebar. Используется как стабильный fallback.

### `copilotkit`

CopilotKit React island + Copilot Runtime. Требует отдельного Node-сервиса и reverse proxy `/copilotkit`.

### `native`

Самописный UI. Базовый вариант должен читать AG-UI-compatible stream напрямую. Если позже потребуется оптимизация, допускается `protocols.native.v1`, но он не должен ломать AG-UI compatibility.

## Protocol metadata

Каждый AG-UI run должен в начале потока отдавать metadata:

```json
{
  "type": "CUSTOM",
  "name": "local_business.protocol",
  "value": {
    "agui_profile": "ag-ui@0.0.55",
    "local_business_protocol": "1.0",
    "driver": "copilotkit",
    "extensions": [
      "ui_command.open_right_panel.v1",
      "page_context.envelope.v1"
    ]
  }
}
```

Клиентские правила:

- неизвестный `CUSTOM` event игнорировать;
- неизвестное поле в known event игнорировать;
- неизвестное расширение не считать ошибкой;
- для несовместимого major показывать понятную ошибку и не выполнять UI-команды.

## Политика версии AG-UI

Текущий AG-UI профиль закреплен в metadata и настройках:

```text
LOCAL_BUSINESS_AI_UI_AGUI_PROFILE=ag-ui@0.0.55
@ag-ui/client=0.0.55
```

При любом изменении серверного AG-UI контура нужно проверить, не вышла ли новая версия AG-UI с изменениями wire contract, схем событий или рекомендаций по streaming. Это обязательная проверка актуальности, но не разрешение на автоматическое обновление.

Порядок:

- проверить `package.json`, `package-lock.json`, `LOCAL_BUSINESS_AI_UI_AGUI_PROFILE` и при необходимости официальные release notes/docs;
- если версия устарела, записать предупреждение в отчет по задаче и оценить риск;
- не менять `@ag-ui/client`, CopilotKit, `agui_profile` и формат событий без согласования с владельцем;
- после согласованного обновления выполнить unit/integration/e2e для `legacy`, `copilotkit`, `native` и обновить ADR/guides/deployment.

## UI-команды

Начальный контракт:

```json
{
  "type": "open_right_panel",
  "version": "1.0",
  "source_code": "workorders",
  "object_type": "work_order",
  "object_id": "123",
  "mode": "view",
  "title": "Заявка #123",
  "htmx_url": "/workorders/123/panel/",
  "target": "#global-right-panel-content",
  "swap": "innerHTML",
  "drawer_size": "default"
}
```

Обязательные проверки:

- `htmx_url` только относительный путь, начинается с `/`, не начинается с `//`;
- команда не выполняет запись;
- видимость объекта проверяется backend-слоем, который формирует URL/данные;
- клиент дедуплицирует команды;
- неизвестные команды игнорируются.

## Совместимость с CopilotKit

Для CopilotKit сохраняется:

- `CopilotRuntime`;
- `HttpAgent`;
- `threadId`;
- `properties/forwardedProps`;
- `STATE_DELTA` для agent state.

Переходная совместимость:

- временно дублировать UI-команды в `/localBusinessUiCommands`;
- новый путь считать основным: `/localBusiness/uiCommands`.

## Совместимость с native UI

Native UI должен уметь:

- отправить AG-UI-compatible `RunAgentInput`;
- прочитать SSE события;
- собрать текст из `TEXT_MESSAGE_*`;
- отобразить tool trace из `TOOL_CALL_*`;
- применить `STATE_DELTA`;
- обработать `local_business.protocol`;
- выполнить только разрешенные `local_business.ui_command`.

## Что взять из CopilotKit в самописный чат

CopilotKit полезен не как обязательная зависимость для основного UI, а как референс готового AG-UI клиента. Для native-чата стоит перенести следующие решения:

### 1. Жизненный цикл run/thread

Взять:

- явное разделение `thread_id`, `run_id`, `message_id`;
- кнопку нового чата с созданием чистой Django `ChatSession`;
- remount/reconnect поведение при смене thread;
- понятные состояния `loading`, `streaming`, `error`, `idle`.

Не брать:

- хранение истории на стороне внешнего hosted runtime;
- скрытое продолжение старой беседы без явного выбора пользователя.

### 2. Потоковая сборка сообщений

Взять:

- обработку `RUN_STARTED`, `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`, `RUN_FINISHED`, `RUN_ERROR`;
- аккуратную сборку assistant-сообщения из частичных событий;
- устойчивость к повторным/частичным SSE chunks;
- отображение частичного ответа без ожидания завершения всего run.

Не брать:

- зависимость UI от внутренних структур React-компонентов CopilotKit;
- логику, которая требует Copilot Runtime для native-режима.

### 3. Tool trace

Взять:

- компактное отображение выполняемого действия;
- статусы tool call start/args/end/result;
- redaction sensitive args до попадания в браузер;
- связь tool trace с `request_id`, `run_id` и audit.

Не брать:

- показ raw tool arguments/result пользователю;
- browser-side tools для доменных write-действий.

### 4. State delta и UI-команды

Взять:

- применение `STATE_DELTA` как канала UI state;
- основной путь `/localBusiness/uiCommands`;
- дедупликацию команд на клиенте;
- выполнение только allow-listed команд;
- игнорирование неизвестных расширений без падения клиента.

Не брать:

- временный compatibility path `/localBusinessUiCommands` как долгосрочный API;
- команды без версии и server-side нормализации.

### 5. Контекст страницы

Взять:

- реактивное обновление page context при смене правой панели;
- передачу только безопасного envelope, а не DOM;
- единый config endpoint для driver, actor/session и capabilities;
- TTL и подпись actor payload.

Не брать:

- cookies, gateway token, raw actor context, UNC paths, полный DOM или лишние PII в browser state.

### 6. Ошибки и отказоустойчивость

Взять:

- перевод отсутствующего LLM key/runtime сбоя в `RUN_ERROR`;
- человекочитаемую ошибку в UI без stack trace;
- сохранение технических кодов ошибки для оператора;
- fallback на `LOCAL_BUSINESS_AI_UI_DRIVER=legacy`.

Не брать:

- HTTP 5xx до начала stream там, где клиент ожидает AG-UI event stream;
- молчаливое зависание в состоянии "Загрузка чата...".

### 7. Сборка и кэширование

Взять:

- версионирование статических assets query string;
- исключение AI UI bundles из cache-first service worker;
- e2e-проверку, что root смонтирован и текстовое поле доступно.

Не брать:

- тяжелый bundle как неизбежную норму для native UI;
- зависимость от Node runtime в production для native-режима.

### Приоритет реализации native-чата

1. AG-UI stream parser и message reducer.
2. Новый чат, thread/run lifecycle и reload-safe session behavior.
3. Tool trace с server-side redaction.
4. `STATE_DELTA`/`CUSTOM` bridge для UI-команд.
5. Page context update bridge.
6. Error/retry UX и offline/runtime states.
7. История сообщений и выбор старых сессий.
8. Тонкий e2e harness для `legacy`, `copilotkit`, `native`.

## Безопасность и приватность

Общие правила:

- не отдавать gateway token в браузер;
- подписывать actor payload HMAC;
- TTL actor payload по умолчанию 900 секунд;
- не принимать client-provided actor без подписи;
- не выполнять frontend write tools;
- не отправлять raw PII, cookies, secrets, UNC paths, полный DOM;
- редактирующие tools остаются в backend и проходят confirmation/audit.

## Этапы реализации

### Этап 1. Документы и ADR

Статус: выполнено.

Результаты:

- ADR-0028;
- архитектурный план;
- активный planning-файл;
- workflow-блок и task packets.

### Этап 2. Django UI runtime foundation

Статус: выполнено.

Вынести из CopilotKit view:

- actor payload builder;
- signature payload;
- signer;
- UI driver resolver;
- общий config payload.

### Этап 3. Agent protocol foundation

Статус: выполнено.

Создать `services/agent_runtime/protocols/`:

- common internal events;
- common UI commands;
- AG-UI v1 schemas/events;
- protocol metadata.

### Этап 4. Refactor CopilotKit driver

Статус: выполнено.

Перевести текущий CopilotKit path на общую основу:

- не менять пользовательское поведение;
- сохранить e2e;
- сохранить `/copilotkit` runtime;
- сохранить fallback.

### Этап 5. Native AG-UI-compatible UI

Статус: выполнено как минимальный sidebar driver.

Добавить самописный UI driver:

- отдельный frontend entrypoint;
- чтение AG-UI SSE;
- отображение сообщений, tool trace и ошибок;
- выполнение только allow-listed UI-команд.

### Этап 6. Verification and deployment profiles

Статус: частично выполнено. Добавлены unit/integration/e2e проверки; production-проверка на целевом deployment остается перед включением пользователям.

Проверить:

- `legacy`;
- `copilotkit`;
- `native`;
- security cases;
- rollback.

## Acceptance checks

- Общий actor signing больше не находится в CopilotKit-specific view.
- `/ag-ui` остается совместимым с CopilotKit.
- Native UI проходит smoke/e2e на том же `/ag-ui`.
- UI driver выбирается настройкой `LOCAL_BUSINESS_AI_UI_DRIVER`.
- AG-UI stream содержит protocol metadata.
- UI-команды имеют версию и allow-list.
- Старый sidebar работает в `legacy` режиме.
- CopilotKit sidebar работает в `copilotkit` режиме.
- Production deployment docs описывают выбор драйвера.

## Проверки

Минимальный набор после реализации:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization -v
npm run build:copilotkit
node --check services/copilot_runtime/server.mjs
E2E_COPILOTKIT_ENABLED=true npm run test:e2e -- --project=chromium --grep "CopilotKit"
LOCAL_BUSINESS_AI_UI_DRIVER=native npm run test:e2e -- --project=chromium --grep "AI UI"
LOCAL_BUSINESS_AI_UI_DRIVER=legacy npm run test:e2e -- --project=chromium --grep "sidebar"
make gen-struct
git diff --check
```
