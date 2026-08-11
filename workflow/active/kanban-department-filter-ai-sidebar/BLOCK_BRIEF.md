# Workflow Brief: kanban-department-filter-ai-sidebar

## Цель

Оставить канбан единственным представлением заявок, перенести иерархию подразделений в
фильтр левой панели и сделать встроенный ИИ-чат сворачиваемым с начальным состоянием
`filters` при каждой загрузке страницы.

## Пользовательская ценность

- меньше режимов и переключений на странице заявок;
- организационный фильтр постоянно виден;
- ИИ-чат доступен одним действием и сохраняет текущую сессию;
- ссылка на канбан воспроизводит выбранный срез.

## Основание

- решение владельца от 2026-08-06;
- `docs/adr/ADR-0037-kanban-department-filter-and-collapsible-ai-sidebar.md`;
- `docs/planning/active/kanban-department-filter-ai-sidebar.md`.

## Read scope

- `apps/workorders/`, `templates/workorders/`, workorders-секции `static/src/`;
- `templates/base.html`, `static/src/css/app.css`;
- `apps/ai/page_context.py`, `static/src/js/page_context.js`;
- `static/src/ai_ui/`, `static/src/copilotkit/`;
- `scripts/e2e/tests/`;
- связанные ADR, architecture, guides, planning и workflow.

## Write scope

Только пути, перечисленные в task packets. Runtime-данные, `.env`, deployments и
контракты прав не изменять.

## Порядок исполнения

1. `01-kanban-query-and-department-read-model`.
2. `02-filter-first-sidebar-shell` после пакета 01.
3. `03-ai-driver-lifecycle-and-page-context` после пакета 02.
4. `04-e2e-security-docs-and-acceptance` после пакетов 01-03.
5. После уточнения владельца от 2026-08-07 пакеты
   `06-device-tree-server-contract` и `07-row-selection-and-resizable-sidebar`
   выполнены параллельно по согласованному read-model контракту.
6. `08-followup-integration-and-acceptance` выполнен после 06/07.
7. `10-visual-sidebar-remediation` выполнен после визуальной проверки владельца.
8. `11-workorder-create-form-autocomplete` выполняется после уточнения формы создания от
   2026-08-11.
9. `09-owner-accepted-archive` только после пакетов 10, 11 и явной приемки владельцем.

Пакеты 01-03 меняют связанные пользовательские контракты и выполняются последовательно,
чтобы не создавать конфликтов в `board.html`, `app.css` и e2e. Независимый проверяющий не
должен изменять код до получения явного write scope пакета 04.

## Инварианты

- любой queryset заявок начинается с `visible_workorders_queryset(user, board)`;
- дерево содержит только `visible_departments_queryset(user)`;
- листья изделий содержат только неархивные объекты из `visible_devices_queryset(user)`;
- browser-выбор и кнопка создания не заменяют серверные `can_create` и валидацию queryset;
- browser state не предоставляет прав;
- автодополнение и POST формы повторно проверяются разрешенными queryset;
- новая заявка всегда создается без исполнителя;
- `filters/chat` не сохраняется между загрузками и не меняет ChatSession;
- чат не размонтируется при сворачивании;
- Django gateway, actor signature, CSRF и allow-list UI-команд сохраняются;
- `native` остается каноническим драйвером, CopilotKit — замороженным эталоном;
- версии AG-UI/CopilotKit не обновляются.

## Критерии приемки

- выполнены все критерии ADR-0037;
- удален отдельный tree-mode, но старый URL безопасно открывает канбан;
- URL, UI, queryset и PageContextEnvelope согласованы для повторяемых фильтров;
- проверены роли с полным и branch-limited доступом, подмена URL и пустые состояния;
- проверены native/CopilotKit, reload, stream-during-collapse, mobile и keyboard;
- выполнен финальный полный `make verify-full`;
- документация актуализирована, блок содержит executor/acceptance reports;
- пакет 10 устранил визуальные дефекты и конфликт resize/collapse;
- пакет 11 упростил создание заявки, добавил безопасное автодополнение и поиск по обоим
  номерам изделия;
- пакет 09 архивировал planning/workflow только после явной приемки владельцем.

## Остаточные риски после технической приемки

- production-развертывание в этом пакете не выполнялось;
- полный CopilotKit runtime локально не запускался, версии и wire contract не менялись;
- архивирование планов и workflow ожидает явной приемки владельцем.
