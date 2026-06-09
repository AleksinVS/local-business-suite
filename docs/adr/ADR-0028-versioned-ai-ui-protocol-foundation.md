# ADR-0028: Версионируемая основа AI UI протоколов

## Статус

Proposed

## Дата

2026-06-09

## Контекст

В проекте уже есть несколько связанных направлений:

- контекстный ИИ-чат в левой панели;
- универсальное открытие правого сайдбара ИИ-ботом;
- модульные AI skills и registry-driven MCP-фасад;
- пилот CopilotKit и AG-UI в основном Django UI.

CopilotKit-пилот добавил рабочий путь:

```text
Django UI
  -> CopilotKit React island
  -> Copilot Runtime
  -> services.agent_runtime /ag-ui
  -> существующий LangGraph agent
  -> Django AI gateway
```

Следующая задача - вести два варианта пользовательского AI UI параллельно:

- CopilotKit/AG-UI как готовый внешний UI/runtime-слой;
- самописный UI, который поддерживает AG-UI и может расширять его проектными возможностями.

Если оставить общие части внутри CopilotKit-ветки, появятся проблемы:

- дублирование подписи actor payload;
- дублирование нормализации UI-команд;
- конфликтующие настройки feature flags;
- две расходящиеся схемы событий;
- сложность выбора варианта для deployment.

## Решение

Создать версионируемую основу AI UI протоколов и считать CopilotKit и самописный UI сменными драйверами поверх нее.

Целевое разделение:

```text
apps.ai.ui_runtime
  -> actor/session context, подписи, TTL, выбор UI-драйвера
  -> allow-list UI-команд
  -> общий config endpoint для браузера

services.agent_runtime.protocols.common
  -> внутренние события агента
  -> capabilities и protocol metadata

services.agent_runtime.protocols.agui
  -> adapter common events -> AG-UI events
  -> AG-UI-compatible input schemas
  -> local_business extensions через CUSTOM и STATE_DELTA

services.agent_runtime.protocols.native
  -> опциональный adapter для самописного UI, если он не читает AG-UI напрямую
```

Внутренний агентский runtime не должен зависеть от CopilotKit. Он должен отдавать общий поток событий, который затем переводится в AG-UI-compatible stream.

Самописный UI должен поддерживать AG-UI как базовый протокол. Проектные расширения оформляются как версионируемый наднабор, а не как несовместимый отдельный протокол.

## Версионирование

Ввести два уровня версии:

```text
agui_profile: ag-ui@<pinned-version>
local_business_protocol: <major>.<minor>
```

`agui_profile` фиксирует совместимость с внешним wire contract AG-UI и используемыми клиентскими библиотеками.

`local_business_protocol` фиксирует проектные расширения:

- UI-команды;
- page context envelope;
- audit hints;
- capabilities;
- сведения о драйвере UI.

Правила совместимости:

- major меняется при несовместимом изменении формы данных или смысла события;
- minor добавляет поля, события или возможности без поломки старых клиентов;
- patch не меняет wire contract и не требует отдельной записи в документах протокола.

## Расширения AG-UI

Стандартные AG-UI события сохраняются в совместимом виде:

- `RUN_STARTED`;
- `RUN_FINISHED`;
- `RUN_ERROR`;
- `TEXT_MESSAGE_START`;
- `TEXT_MESSAGE_CONTENT`;
- `TEXT_MESSAGE_END`;
- `TOOL_CALL_START`;
- `TOOL_CALL_ARGS`;
- `TOOL_CALL_END`;
- `TOOL_CALL_RESULT`;
- `STATE_SNAPSHOT`;
- `STATE_DELTA`;
- `CUSTOM`.

Проектные расширения передаются только через безопасные каналы:

```text
CUSTOM name="local_business.protocol"
CUSTOM name="local_business.ui_command"
STATE_DELTA path="/localBusiness/..."
```

Временный путь `/localBusinessUiCommands` разрешен только как переходная совместимость для текущего CopilotKit island. Целевой путь:

```text
/localBusiness/uiCommands
```

Пример protocol metadata:

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

## Выбор UI-драйвера

Вместо boolean-флага для каждого варианта использовать общий выбор драйвера:

```text
LOCAL_BUSINESS_AI_UI_DRIVER=legacy|copilotkit|native
```

Поведение:

- `legacy` - текущий Django/HTMX sidebar;
- `copilotkit` - CopilotKit React island и Copilot Runtime service;
- `native` - самописный UI, предпочтительно AG-UI-compatible без Copilot Runtime.

CopilotKit-специфичные настройки остаются отдельными и действуют только для драйвера `copilotkit`.

## Границы безопасности

Общие для всех драйверов правила:

- браузер не получает Django AI gateway token;
- actor/session context подписывается Django и проверяется agent runtime;
- write-действия идут только через backend tools, policies, confirmation flow и audit;
- frontend UI tools ограничены безопасными действиями интерфейса;
- AG-UI/custom events не содержат raw PII, секреты, cookies, UNC paths, полный DOM или полный actor context;
- неизвестные расширения клиент обязан игнорировать без ошибки.

## Альтернативы

### Держать CopilotKit и native UI в отдельных ветках без общей основы

Отклонено. Это ускоряет первый эксперимент, но приведет к конфликтам в actor context, UI commands, тестах и deployment-профилях.

### Сделать самописный UI на полностью отдельном протоколе

Отклонено. AG-UI уже покрывает lifecycle, текст, tool calls, state updates и custom events. Отдельный протокол увеличит стоимость поддержки без достаточной выгоды.

### Влить CopilotKit-пилот как основной интерфейс и писать native позже

Отклонено до приемки владельцем. В проекте нужен сравнимый вариант без зависимости от внешнего UI/runtime слоя.

## Последствия

Положительные:

- общий агентский и безопасностный контур развивается один раз;
- CopilotKit и native UI можно сравнивать честно, без разных backend-реализаций;
- deployment выбирает UI-драйвер настройкой;
- будущие клиенты могут использовать AG-UI-compatible endpoint;
- проектные расширения получают понятную политику совместимости.

Отрицательные:

- нужен дополнительный рефакторинг текущей CopilotKit-ветки;
- потребуется матрица e2e для `legacy`, `copilotkit` и `native`;
- придется поддерживать protocol metadata и обратную совместимость расширений;
- часть существующих имен `copilotkit_*` нужно перенести в нейтральный слой.

## Требования к реализации

- Создать `apps/ai/ui_runtime/` только для Django-side общей логики UI-драйверов.
- Создать `services/agent_runtime/protocols/` для версионируемых protocol adapters.
- Сохранить текущие `/chat` и `/chat/stream` до отдельной приемки.
- Сохранить `/ag-ui` как AG-UI-compatible endpoint.
- Добавить protocol metadata event.
- Перевести `localBusinessUiCommands` на `/localBusiness/uiCommands` с переходной совместимостью.
- Добавить тесты совместимости событий и подписи actor payload.
- Добавить e2e для выбора драйвера UI.
- Обновить deployment-документацию после реализации.
