# Универсальное открытие правого сайдбара ИИ-ботом

## Статус

Implemented MVP.

Архитектурное решение: `docs/adr/ADR-0020-universal-right-drawer-ai-navigation.md`.

Workflow-блок: `workflow/active/universal-right-drawer-ai-navigation/`.

## Цель

Сделать так, чтобы ИИ-бот мог открывать правый сайдбар с объектом любого подключенного модуля, не дублируя код модулей в AI-ядре.

Примеры:

- открыть заявку из канбан-доски по номеру или id;
- открыть запись листа ожидания;
- открыть объект, найденный через `memory.search` или доменный search-tool;
- сделать это на странице `AI чат`, где сейчас нет правой модульной панели.

## Пользовательская ценность

- Пользователь просит ИИ "открой эту заявку", и система открывает карточку справа.
- ИИ может переходить от поиска/аналитики к конкретному объекту без ручной навигации.
- Новые модули подключают свое открытие через небольшой provider, не меняя AI runtime.
- Открытый объект сразу становится текущим контекстом окна для `ui.get_current_context`.

## Принципы

1. Общий слой отвечает только за контейнер, реестр и доставку UI-команды.
2. Модуль сам отвечает за объект, права, шаблон и detail partial.
3. AI не передает произвольный URL и не получает право обходить доменные policies.
4. `SourceAdapter` не расширяется HTML/UI обязанностями.
5. Открытие панели не является записью бизнес-данных и не требует confirmation flow.
6. Любые будущие write-операции остаются отдельными tools с подтверждением.
7. MVP не вводит универсальную платформу событий.

## Не цели

- Не строить универсальный CRUD.
- Не переносить все drawer-формы в один общий framework.
- Не делать event bus/outbox.
- Не открывать произвольные внешние URL.
- Не смешивать `SourceAdapter` памяти/аналитики с UI-provider.
- Не добавлять редактирование, создание и переходы статусов в `ui.open_right_panel`.

## Целевая архитектура

```text
Пользователь просит ИИ открыть объект
  -> agent runtime вызывает ui.open_right_panel
  -> Django AI gateway проверяет tool registry
  -> RightPanelProvider registry находит provider
  -> provider проверяет доступ и строит RightPanelDescriptor
  -> tool result возвращает UI command
  -> browser chat client исполняет UI command
  -> HTMX загружает модульный partial в global drawer
  -> PageContextEnvelope обновляет selection
```

## Контракты

### RightPanelDescriptor

Минимальные поля:

```json
{
  "type": "open_right_panel",
  "source_code": "workorders",
  "object_type": "workorder",
  "object_id": "123",
  "mode": "view",
  "title": "Заявка 123",
  "htmx_url": "/workorders/123/",
  "target": "#global-right-panel-content",
  "swap": "innerHTML",
  "drawer_size": "large",
  "context_hint": "workorders / workorder#123"
}
```

### RightPanelProvider

Минимальный Python-интерфейс:

```python
class RightPanelProvider(Protocol):
    source_code: str
    object_type: str
    supported_modes: tuple[str, ...]

    def can_open(self, user, object_id: str, mode: str = "view") -> bool:
        ...

    def build_panel(self, user, object_id: str, mode: str = "view") -> RightPanelDescriptor:
        ...
```

Рекомендуемое размещение:

- общий интерфейс и registry: `apps/core/right_panels.py`;
- регистрация provider в `apps.<module>.apps.AppConfig.ready()`;
- module providers: `apps/workorders/right_panel.py`, `apps/waiting_list/right_panel.py`.

## Этапы реализации

### Этап 1. Контракт provider и registry

Статус: выполнено.

Задачи:

- добавить `RightPanelDescriptor`;
- добавить `RightPanelProvider` protocol;
- добавить функции `register_right_panel_provider`, `get_right_panel_provider`, `registered_right_panel_providers`;
- добавить валидацию `source_code`, `object_type`, `mode`;
- сделать fail-closed поведение для неизвестных provider и mode.

Проверки:

```bash
python manage.py test apps.core.tests
python manage.py check
```

### Этап 2. Общий drawer-host и browser bridge

Статус: выполнено.

Задачи:

- добавить общий right drawer в `templates/base.html`;
- добавить `static/src/js/right_panel.js`;
- реализовать `window.LocalBusinessRightPanel.open(command)`;
- поддержать HTMX-загрузку descriptor `htmx_url -> target`;
- после успешной загрузки вызвать `LocalBusinessPageContext.refresh()`;
- сохранить текущие локальные функции `openKanbanDrawer`, `openWaitingListDrawer` как совместимые wrappers или мигрировать их на общий API.

Проверки:

```bash
python manage.py check
npm run test:e2e -- --project=chromium
```

### Этап 3. Провайдеры `workorders` и `waiting_list`

Статус: выполнено.

Задачи:

- `workorders` provider:
  - `source_code=workorders`;
  - `object_type=workorder`;
  - `mode=view`;
  - доступ через существующие selectors/policies;
  - `htmx_url` на существующий detail partial.
- `waiting_list` provider:
  - `source_code=waiting_list`;
  - `object_type=waiting_list_entry`;
  - `mode=view`;
  - доступ через существующие waiting-list policies;
  - `htmx_url` на существующий detail partial.
- добавить `data-ai-context` в waiting-list detail partial, если его еще нет, чтобы открытие записи обновляло selection.

Проверки:

```bash
python manage.py test apps.workorders.tests apps.waiting_list.tests
python manage.py test apps.ai.tests
```

### Этап 4. AI tool `ui.open_right_panel`

Статус: выполнено.

Задачи:

- добавить tool в `contracts/ai/tools.json` и `apps/ai/tool_definitions.py`;
- добавить dispatch в `apps/ai/tooling.py`;
- добавить wrapper в `services/agent_runtime/tools.py`;
- обновить runtime prompts: tool вызывать только когда пользователь просит открыть/показать объект в интерфейсе;
- обеспечить доставку UI-команды в browser chat client для full-page и sidebar чата;
- не требовать confirmation, так как tool меняет только UI state.

Проверки:

```bash
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization
```

### Этап 5. E2E и документация

Статус: выполнено в коде и документации; e2e-сценарии добавлены в постоянный набор.

Задачи:

- e2e: с главной страницы/доски открыть заявку через обычный click после миграции на общий drawer;
- e2e: со страницы `AI чат` вызвать UI-команду и открыть заявку справа;
- e2e: открыть запись листа ожидания справа;
- проверить отказ доступа;
- обновить пользовательское руководство по AI sidebar/chat.

Проверки:

```bash
npm run test:e2e -- --project=chromium
python manage.py check
python manage.py validate_architecture_contracts
make gen-struct
```

## Данные и безопасность

- Tool не возвращает полный HTML в runtime.
- Tool не принимает URL от модели.
- Все URL строятся provider на сервере.
- Provider обязан проверить доступ до выдачи descriptor.
- Если provider отсутствует, ответ должен быть понятным: объект нельзя открыть в UI.
- Аудит tool call не должен хранить PII из объекта. Достаточно `source_code`, `object_type`, `object_id`, `mode`, status/error.
- Открытие панели обновляет контекст окна, но сервер заново проверяет selection при `ui.get_current_context`.

## Критерии готовности

- На странице `AI чат` можно открыть справа заявку и запись листа ожидания.
- Обычные клики по заявкам и листу ожидания продолжают работать.
- Новый модуль может подключиться добавлением provider без правки AI runtime.
- Неизвестный provider и чужой объект не открываются.
- `PageContextEnvelope` после открытия содержит корректный `selection`.
- Tool registry и архитектурные контракты валидны.

## Итог реализации

Реализованы:

- общий `RightPanelProvider` registry в `apps.core.right_panels`;
- модульные providers для заявок и листа ожидания;
- общий правый сайдбар на всех страницах;
- browser bridge для безопасных команд `open_right_panel`;
- AI tool `ui.open_right_panel`;
- доставка `ui_command` через потоковый full-page и sidebar чат;
- server-side resolver контекста для `waiting_list/waiting_list_entry`;
- unit-тесты provider registry, модульных providers, gateway tool и runtime wrapper;
- e2e-сценарии открытия заявки и записи листа ожидания из страницы `AI чат`.

Ограничение MVP остается прежним: общий инструмент только открывает просмотр объекта (`mode=view`). Запись бизнес-данных выполняется отдельными доменными инструментами и views.
