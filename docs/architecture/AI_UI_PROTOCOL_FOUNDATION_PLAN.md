# Версионируемая основа AI UI протоколов

## Статус

Proposed. Документ описывает следующий этап после первого CopilotKit/AG-UI среза. Реализация еще не выполнена.

Связанные документы:

- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md`;
- `docs/adr/ADR-0027-copilotkit-ag-ui-django-integration.md`;
- `docs/architecture/COPILOTKIT_AG_UI_INTEGRATION_PLAN.md`;
- `docs/planning/active/ai-ui-protocol-foundation.md`;
- `workflow/active/ai-ui-protocol-foundation/`.

## Методологическая заметка

Протокол интерфейса - это контракт между backend и UI. Если UI-библиотека становится этим контрактом напрямую, любая смена UI тянет за собой backend. Поэтому проекту нужен внутренний стабильный слой событий и отдельные адаптеры: один для CopilotKit/AG-UI, второй для самописного AG-UI-compatible UI.

## Цель

Сделать так, чтобы CopilotKit/AG-UI и самописный AI UI развивались параллельно поверх общей основы:

- один actor/session context;
- один набор безопасных UI-команд;
- один внутренний поток агентских событий;
- один AG-UI-compatible wire contract;
- версионируемые проектные расширения;
- выбор UI-варианта через настройки deployment.

## Non-goals

- Не переписывать агентскую orchestration.
- Не переносить бизнес-логику в Copilot Runtime или frontend.
- Не удалять текущий HTMX sidebar до приемки.
- Не включать Copilot Cloud, hosted persistence или внешнюю аналитику.
- Не добавлять browser-side write tools.

## Текущая отправная точка

В ветке CopilotKit-пилота уже есть:

- `services.agent_runtime /ag-ui`;
- `services/agent_runtime/ag_ui_adapter.py`;
- `services/copilot_runtime/server.mjs`;
- React island `static/src/copilotkit/main.jsx`;
- Django endpoint `/ai/chat/copilotkit/config/`;
- HMAC-подписанный actor payload;
- feature flag `LOCAL_BUSINESS_COPILOTKIT_ENABLED`;
- e2e для CopilotKit sidebar.

Ограничения текущего состояния:

- общий actor signing находится рядом с CopilotKit-specific view;
- UI driver выбирается boolean-флагом;
- frontend command path привязан к `localBusinessUiCommands`;
- нет protocol metadata event;
- нет отдельного места для common/internal events;
- native UI пока не имеет собственного execution path.

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
  +--> native AG-UI UI

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
  commands.py
  config.py
  drivers.py
  schemas.py
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
    events.py
    ui_commands.py
  agui/
    __init__.py
    v1.py
    events.py
    schemas.py
  native/
    __init__.py
    v1.py
```

Назначение:

- нормализовать входной запрос;
- проверить подпись actor payload;
- описать внутренние события;
- перевести внутренние события в AG-UI;
- добавить project extensions без нарушения AG-UI-compatible клиентов.

## UI-драйверы

Целевая настройка:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy|copilotkit|native
```

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

Статус: этот документ.

Результаты:

- ADR-0028;
- архитектурный план;
- активный planning-файл;
- workflow-блок и task packets.

### Этап 2. Django UI runtime foundation

Вынести из CopilotKit view:

- actor payload builder;
- signature payload;
- signer;
- UI driver resolver;
- общий config payload.

### Этап 3. Agent protocol foundation

Создать `services/agent_runtime/protocols/`:

- common internal events;
- common UI commands;
- AG-UI v1 schemas/events;
- protocol metadata.

### Этап 4. Refactor CopilotKit driver

Перевести текущий CopilotKit path на общую основу:

- не менять пользовательское поведение;
- сохранить e2e;
- сохранить `/copilotkit` runtime;
- сохранить fallback.

### Этап 5. Native AG-UI-compatible UI

Добавить самописный UI driver:

- отдельный frontend entrypoint;
- чтение AG-UI SSE;
- отображение сообщений, tool trace и ошибок;
- выполнение только allow-listed UI-команд.

### Этап 6. Verification and deployment profiles

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
