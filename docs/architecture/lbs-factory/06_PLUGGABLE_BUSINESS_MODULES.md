# Подключаемые бизнес-модули: миграция Kanban, Waiting List, Warehouse

Статус: **целевая спецификация и миграционный план, не реализация**. Версия LBS Factory v3.2, 2026-10-12.

## 1. Принятое решение

Все три функциональные области существующего LBS должны стать **подключаемыми и отключаемыми компонентами**:

- **Kanban** — опциональное представление/расширение управления задачами; текущий код встроен в `apps.workorders`, поэтому отделять сначала **по функциональной границе**, не переносить бездумно таблицы и операции в отдельный сервис; связь `WorkOrder.board` требует отдельного плана сохранения данных.
- **Waiting List** (`apps.waiting_list`) — отдельный предметный компонент с собственным API, политикой доступа и данными.
- **Warehouse** (`apps.warehouse`) — отдельный предметный компонент со своим транзакционным ядром склада, движениями и проекцией остатков.

Они не должны требоваться для запуска Factory, чата, агентов, LLM-Wiki, интеграций или друг друга. Каждый должен иметь автономные тесты, корректное выключение, декларацию прав и стабильные точки интеграции. **Независимо включаемый модуль не обязательно равен микросервису.** Изначально допустим модуль в общем Django-процессе с совместной PostgreSQL; вынесение в процесс/БД — поздний и отдельно проверяемый этап.

## 2. Уточнение терминов

| Состояние | Смысл | Базовые гарантии |
|---|---|---|
| `available` | Компонент присутствует в сборке | Никаких разрешений пользователю само по себе не даёт |
| `enabled` | Конфигурация установки включает capability | Инициализируются маршруты, меню, задания и публичные операции |
| `authorized` | Пользователь/агент имеет конкретные права на действие | Предметные проверки продолжают действовать, даже если capability включено |
| `disabled` | Код/таблицы могут оставаться, функция недоступна | Никаких новых пользовательских операций, данных не удаляем |
| `uninstalled` | Пакет отсутствует в составе сборки | Допускается только после удаления всех прямых runtime-импортов и проверки миграций; удаление данных отдельно |

**Важно:** признак в конфигурации не является защитой от прямого URL/API/MCP-вызова. Fail-closed на всех входах. Не путать `disabled` с `read-only maintenance` и с `uninstalled`.

## 3. Что проверено в текущем коде

| Область | Наблюдаемая связность | Следствие для миграции |
|---|---|---|
| `config/settings.py`, `config/urls.py` | Apps и URL перечислены непосредственно в центральных конфигурациях | Перейти к регистрации manifest/route contributions; переходный список допустим |
| `apps/workorders/models.py` | `WorkOrder.board` связан с `Board`; `Board`, `KanbanColumnConfig`, `WorkOrder` сейчас в одном приложении | **Kanban нельзя просто выключить:** `WorkOrder.board` сейчас обязательный FK с `on_delete=CASCADE` (удаление доски может удалить заявки); нужно отделить базовые задания от способа их отображения и проверить существующие обязательные связи |
| `apps/workorders/models.py` | `WorkOrder` связан с `Department`, пользователями и `MedicalDevice` | Общие идентичности и device lookup должны быть контрактами/провайдерами, а не обязательными импортами для всего Factory |
| `apps/waiting_list/services.py` | Зависит от `apps.workorders.policies.role_rules` | Убрать предметную зависимость. Waiting List регистрирует собственные capabilities и проверяет scope через общий auth contract |
| `apps/warehouse/models.py` | Множество связей с `Department`/пользователем; собственные `StockEntry` и `StockBalance` | Отделить provider контекста организации/identity; **не разбивать проведение на несколько сервисов** |
| `apps/accounts/access_contracts.py`, `apps/core/contract_store.py` | Импортируют политики/контракты предметных приложений | Убрать обратную зависимость ядра от конкретных модулей; домены сами регистрируют метаданные |
| `apps/workorders/apps.py` | Уже регистрирует skills, autocomplete, right-panel и source adapter | Использовать существующие точки входа как переходный механизм, не создавать параллельные реестры |

Ссылки: `https://github.com/AleksinVS/local-business-suite/blob/main/apps/workorders/models.py`, `.../apps/waiting_list/services.py`, `.../apps/warehouse/models.py`, `.../config/settings.py`. Перед исполнением проверить HEAD репозитория и корректировать точные строки.

## 4. Логическая архитектура после выделения

```text
LBS Factory kernel (без зависимостей от предметных модулей)
    |-- registry / capability contracts / identity context / configuration
    |-- KnowledgeProvider (LLM-Wiki optional)
    |-- AgentTask / A2A adapters (optional runtime)
    +-- module contributions (routes, nav, skills, tools, permissions, events)

Optional domain packages:
    task-domain (provider или адаптер сторонней task-системы)
      +-- workorders (предметный task service, optional)
            +-- kanban-view (UI/board extension, optional)
    waiting-list (optional, independent domain)
    warehouse (optional, independent ledger domain)

Provider choices:
    TaskProvider = bitrix24 | vikunja | openproject | lbs-workorders
    Organization/Identity provider = local | LDAP/OIDC/AD | ...
```

Канбан — **способ представления и перемещения заданий**, не самостоятельная универсальная система всех бизнес-процессов. Не смешивать его с `AgentTask` (делегирование между агентами) или `Job` (техническая очередь). Внешний TaskProvider допускается **только если операция соответствует его контракту**. Если WorkOrders имеет специфичные поля ремонта/оборудования, не превращать их в универсальные обязательные поля TaskProvider.

## 5. Минимальный контракт модуля

Начальный манифест — **статический и проверяемый**; допускается Python descriptor вместо YAML, без динамической установки произвольного кода.

```yaml
id: warehouse
version: 1.0.0
platform_api: '1.x'
capabilities: [warehouse.view, warehouse.receive, warehouse.issue]
requires: [identity]
optional_integrations: [knowledge.search, agent.tools, notifications]
runtime: in_process
```

Правила:

1. Registry содержит только descriptors и providers. **Kernel не импортирует** `apps.warehouse`, `apps.waiting_list`, `apps.workorders` ради определения прав или поведения.
2. Публичный контракт каждого модуля: `capabilities`, схемы входа/выхода (на первом этапе Python types/JSON Schema), `policies`, `routes`, `menu`, `health`, `version`, `data_owner`, `migrations`, `deactivation_policy`.
3. Не каждый пункт требует отдельного интерфейса или класса: используем уже существующие registries там, где они соответствуют контракту.
4. Модуль может поставлять Skills/Agent Tools через регистрацию; **невключённый модуль не объявляет доступных tools** агентам.
5. Вызовы между доменами — через явный port/API. В рамках Django допускается прямой Python-вызов публичного интерфейса; **прямой импорт чужого ORM для новой логики запрещён**.
6. Фоновое задание, приём webhook и выполнение команд требуют повторной проверки `enabled + authorization`, даже если запрос уже прошёл Gateway.
7. Данные модулей не теряются от переключения профиля. Отдельный `export/migrate/retire` workflow необходим для окончательного удаления.

## 6. WorkOrders/Kanban: специальная декомпозиция

### 6.1 Не делать «выключатель доски» поверх обязательной модели `WorkOrder.board`

Сначала определить, какой минимум заявки существует без Kanban: identity, название/описание, статус, исполнитель, автор, scope и история. `Board` и колонки относятся к *представлению и настройке маршрутов* — но `WorkOrder.board` сейчас является частью предметной модели. Требуется сохранить существующие данные и семантику перемещений при создании нового API.

Возможные варианты после инвентаризации:

- **Рекомендуемый первый этап:** общий `workorders` пакет сохраняет схему, но Kanban routes/templates/board UX разрешаются только при включённом `kanban-view`; основной list/detail API работает без Kanban. Отдельный `tasks.kanban` пакет создаётся лишь после того, как его можно подключить без миграций ядра WorkOrders.
- **Позже:** выделить отдельную модель `BoardPresentation/TaskBoardLink` или эквивалентную проекцию, перевести обязательную FK на необязательную/переходную связь, ввести миграцию `expand -> backfill -> cutover -> contract`. Менять модель только после подтверждения требований и обратимости миграции.
- **При Bitrix24 TaskProvider:** использовать канбан Битрикс24 напрямую или отдельный read model/синхронизатор; **не вести независимую вторую истину о задачах**, и не предполагать полное совпадение его workflow с WorkOrders.

### 6.2 Планируемые минимальные API

`workorders.list/get/create/transition` — отдельный предметный интерфейс (если workorders установлен); `kanban.get_board/move_card` — UI-представление поверх доступных команд TaskProvider, с явным отказом при отсутствии поддержки. Нельзя использовать произвольное редактирование полей задач для обхода разрешённых переходов.

## 7. Waiting List: независимость без ложного «общего workflow»

- Убрать зависимость `waiting_list.services -> workorders.policies`; policy и capabilities принадлежат Waiting List и общему `AuthorizationProvider`.
- Лист ожидания должен функционировать **без установленного WorkOrders**, а передача принятой записи в заявку — необязательный адаптер `waiting-list-to-workorders` / `waiting-list-to-bitrix-task`.
- Создание заявки из записи должно быть идемпотентным; связь хранить через external reference / mapping; сбой получателя не должен уничтожать исходную запись.
- Общий UI и статусы не означают общий движок workflow; Waiting List владеет собственными состояниями и историей.

## 8. Warehouse: самостоятельность без разрушения учёта

- Сохранить `StockDocument`, `StockEntry` и `StockBalance` в **одной транзакционной границе**. Не декомпозировать `posting` на сетевые микросервисы.
- Использовать `Identity/OrganizationPort` для проверки подразделения/прав и (при выделении самостоятельного процесса) стабильные внешние IDs вместо прямых Django FK; не заменять все FK заранее без необходимости.
- Модуль должен поддерживать `disabled` без потери уже проведённых операций и без запуска регламентных/интеграционных заданий.
- Интеграции с 1C/Bitrix и LLM-Wiki — потребители или поставщики типизированных событий/проекций; не прямые правки журнала движения.
- Не превращать warehouse в обязательный `InventoryProvider` всей Factory: у заказчика может существовать внешняя WMS/1С; выбор владельца остатков — в конфигурации внедрения.

## 9. Миграция без остановки существующих установок

| Шаг | Делать | Не делать | Приёмка |
|---|---|---|---|
| M0 | Dependency map: imports, FK, settings, URLs, nav, tools, migrations, данные и права | Код менять вслепую | Карта границ и rollback plan |
| M1 | Добавить статический registry/manifest поверх существующих apps | Сразу hot-install пакетов | Старый профиль работает без изменений |
| M2 | Убрать обратные импорты Kernel/Accounts к предметным modules | Менять RBAC-инварианты | Без трёх модулей registry/core импортируется и проходит checks |
| M3 | Waiting List: собственные политики + optional handoff adapter | Принудительная интеграция с WorkOrders | Работает без WorkOrders |
| M4 | WorkOrders/Kanban: разделить business/task API и board UI | Разрывать `WorkOrder.board` без migration plan | List/detail работает при выключенном Kanban; board on — без регрессии |
| M5 | Warehouse: ports для org/identity, независимые регистрацию/меню/AI tools | Выносить posting через сеть | Проводки/остатки сохранены, модуль выключается безопасно |
| M6 | Профили `minimal`, `kanban-only` (если позволяет контракт), `waiting-list`, `warehouse`, `full`, `bitrix-tasks` | Считать выключение удалением данных | Матрица комбинаций проходит e2e |
| M7 | Упаковка/независимое развёртывание по потребности | Автоматическое разбиение БД и сервисов | Модуль ставится без правок ядра; экспорт/rollback проверены |

Модули удаляются из `INSTALLED_APPS` **только после анализа Django migration dependencies**. На первых этапах `disabled` означает запрет использования, но не физическое отсутствие app и таблиц. В последующих профилях пустого ядра проверять, что `makemigrations --check`, `migrate`, `check`, API и static сборка работают без удалённых пакетов.

## 10. Сквозная проверка (минимум)

**Профиль без модулей:** kernel, IdentityProvider, Wiki/Agents (по выбору) стартуют, в UI/API/MCP нет ссылок на Kanban, Waiting List, Warehouse. Доступ по прямому URL/APIs закрыт, workers не активируются.

**Профиль Waiting List без WorkOrders:** создать/получить/изменить статус записи, политика и аудит действуют, нет импорта `apps.workorders`.

**Профиль WorkOrders без Kanban:** создать и открыть заявку через list/detail API; данные старых заявок сохраняются. При включении Kanban показываются те же заявки.

**Профиль Warehouse:** поступление, расход, отрицательный остаток запрещён, операция идемпотентна, история не меняется; выключить/включить модуль, проверить неизменность проводок.

**Профиль Bitrix Tasks:** TaskProvider = Bitrix24; Kanban/WorkOrders не создают локальный параллельный источник истины; агентов не знакомят с инструментами отключённых модулей.

**Безопасность:** каждая операция проходит `enabled` + предметную авторизацию; скомпрометированное состояние UI или недоверенная A2A/MCP нагрузка не могут обойти эту проверку.

## 11. Критические риски и правила упрощения

1. **Не путать функциональные и физические модули.** Вначале ограничиваем доступ к уже имеющимся Django apps; отдельные репозитории/сервисы — позднее.
2. **Не вводить универсальную ORM или общий BPMN.** Регистрировать только публичные возможности.
3. **Не выносить warehouse ledger в async-сеть** ради независимости; атомарный учёт важнее красивой схемы.
4. **Не превращать Kanban в обязательное хранилище задач.** Это способ просмотра над доменным источником.
5. **Не переписывать всю систему заново.** Переносить по одной функции через стабильный API и проверяемый rollback.
6. **Не дублировать TaskProvider, AgentTask и QueueJob.** Это разные доменные объекты.
7. **Не поддерживать произвольные несовместимые комбинации.** В registry обязательные/опциональные зависимости и декларативно поддерживаемые профили; тестируем именно их.

## 12. Задания coding-агентам

| ID | Задание | Вход/граница записи | Условие завершения |
|---|---|---|---|
| BM-00 | Dependency inventory + ADR | read all; write docs only | граф imports/FK/routes/permissions + migration plan |
| BM-01 | Minimal module descriptor/registry | shared registration code and tests only | `enabled` gate по всем входам, no runtime import from disabled provider |
| BM-02 | Waiting List decoupling | `apps/waiting_list`, cross-app policy adapters | нет прямого workorders policy import, standalone e2e |
| BM-03 | WorkOrders/Kanban boundary | `apps/workorders`, templates/routes, migration only when approved | kanban off while workorders list/detail works |
| BM-04 | Warehouse decoupling | `apps/warehouse`, identity/org adapter | intact ledger invariants and disable e2e |
| BM-05 | Provider & AI registry projection | tool catalog, skills, registry adapters | no tools from disabled modules, no double registry canon |
| BM-06 | Profile and upgrade acceptance | deploy test fixtures, CI, docs | no-modules & mixed profiles pass including rollback |

**Не запускать BM-02/BM-03/BM-04 с общими правками `apps.core` одновременно**, если нет предварительно согласованного контракта и изоляции изменяемых файлов. На все рискованные изменения — независимая проверка ролей, миграций данных и сценарием отключения. Следовать `AGENTS.md`, ADR и текущей политике тестирования репозитория.

## 13. LBS Access и независимость предметных модулей (v3.3)

Обязательная часть module extraction — **отвязать общий role/grant resolver от WorkOrders**. `apps.accounts.services`/`access_contracts` не должны импортировать `apps.workorders.policies`; `apps.warehouse.policies` и `apps.waiting_list.services` должны пользоваться нейтральным access port. Это *предварительное условие* истинной опциональности Waiting List/Warehouse.

- Каждый бизнес-модуль регистрирует декларативные capabilities (`flag/scope/targets`, labels, protected info, schema version) без автоматического назначения ролей.
- Общий `AuthorizationProvider` возвращает существующие grants; домен **сам** решает по объекту, состоянию и ACL. Не вводить generic policy DSL и не выносить warehouse ledger authorization отдельно от транзакции.
- При `disabled` grants хранятся, но доступ через HTTP/UI/AI/MCP/worker не предоставляется; повторное включение — не миграция старых назначений с новыми значениями.
- Отдельная миграция role documents в PostgreSQL не входит в работу по отключаемости бизнес-модулей.

Связанные детальные спецификации: `07_ACCESS_ARCHITECTURE.md` и `08_ACCESS_MIGRATION_AND_TESTS.md`. Задания BM-01/BM-02/BM-04 согласовать по write scope с AX-01/AX-02/AX-03 до старта coding agents.
