# Workflow Brief: context-aware-sidebar-ai-chat

Статус: implemented, awaiting owner acceptance.

Дата: 2026-05-28.

## Цель

Подготовить реализацию контекстного ИИ-чата в левой боковой панели:

- меню левого сайдбара переносится в выпадающее меню `Все функции` в верхнем левом блоке;
- левый сайдбар занимает встроенный ИИ-чат;
- чат получает контекст текущей страницы, модуля, фильтров и выбранной сущности;
- открытая в правом drawer карточка заявки становится текущей selection для ИИ.
- встроенный чат использует отдельную sidebar-сессию с compact/summarization;
- панель поддерживает режимы pinned/collapsed.

## Архитектурные источники

- `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`
- `docs/planning/active/context-aware-sidebar-ai-chat.md`
- `docs/adr/ADR-0003-ai-memory-service.md`
- `docs/adr/ADR-0007-settings-center-and-contextual-help.md`
- `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`

## Read scope

- `templates/base.html`
- `templates/ai/`
- `templates/workorders/`
- `static/src/js/ai_chat.js`
- `static/src/css/app.css`
- `apps/ai/`
- `apps/workorders/`
- `apps/memory/`
- `apps/analytics/`
- `apps/waiting_list/`
- `contracts/ai/`
- связанные docs/guides после реализации

## Write scope

Ожидаемый write scope при реализации:

- `templates/base.html`
- `templates/ai/` и новые reusable partials;
- `static/src/js/ai_chat.js` или новый общий chat module;
- новый `static/src/js/page_context.js`;
- `static/src/css/app.css`;
- `apps/ai/` для envelope validation/resolution и передачи контекста runtime;
- точечные шаблоны модулей для `data-ai-context`;
- tests в `apps/ai/tests.py`, `apps/workorders/tests.py` и e2e;
- docs/guides после реализации.

## Non-goals

- Не вводить полноценный event bus/event store в MVP.
- Не хранить каждое действие UI как событие.
- Не передавать полный HTML страницы в ИИ.
- Не обходить доменные права доступа через client-side context.
- Не передавать полный context envelope в каждый prompt, если достаточно `window_id/context_version`.
- Не читать latest window context для уже отправленного сообщения; использовать только snapshot, привязанный к message/request.

## Ключевое решение

MVP использует `PageContextEnvelope`, browser context bridge и read-only tool `ui.get_current_context`. Браузер публикует снимок окна на сервер, а ИИ вызывает tool только когда ответ зависит от текущего окна. Полноценная универсальная платформа событий откладывается до появления нескольких подписчиков, требований надежной доставки или общего activity stream.

Контекст должен быть immutable для конкретного сообщения: при submit backend связывает `ChatMessage` с `context_snapshot_id`, а `ui.get_current_context` читает этот bound snapshot.

## Acceptance

- Все пункты текущего меню доступны через `Все функции`.
- В левом сайдбаре есть компактный ИИ-чат.
- Встроенный чат использует отдельную sidebar-сессию.
- Sidebar-сессия compact/summarization оставляет последние N сообщений и summary старой части.
- Лимиты истории и суммаризации задаются через общий runtime contract `ai.chat_settings`.
- N для sidebar берется из `surfaces.sidebar.recent_message_limit`, по умолчанию `8`.
- Основной и sidebar chat читают эффективные настройки через общий helper, без отдельной дублирующей настройки.
- В sidebar нет переключателя сессий; история и выбор других диалогов остаются на полной странице чата.
- UI просмотра/ручной перегенерации summary не входит в MVP.
- Избранное остается в верхней панели.
- Левая панель поддерживает pinned/collapsed режим.
- При открытии workorder drawer чат отправляет `source_code=workorders` и `object_id` текущей заявки.
- Сервер заново проверяет доступ к выбранному объекту.
- Вопрос `что с этой заявкой?` использует текущую карточку через `ui.get_current_context`.
- Если пользователь отправил вопрос по заявке A и сразу открыл заявку B, ответ первого запроса использует snapshot заявки A.
- Expired window snapshots очищаются cleanup command/job.
- Client-provided capabilities не принимаются как права.
- Write actions остаются через confirmation flow.
- Без контекста чат работает как раньше.

## Verification

Минимум:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.ai.tests apps.workorders.tests
npm run test:e2e
```

Дополнительно:

- скриншоты desktop/mobile для меню `Все функции`;
- скриншоты sidebar chat на доске и с открытой карточкой;
- e2e на контекст открытой карточки.

## Итог исполнения

Кодовый MVP реализован 2026-05-28. Детальный контекст выбранной сущности реализован для `workorders`; остальные модули получают базовый route context и требуют отдельных selection-resolvers при развитии сценариев.

Фактические проверки зафиксированы в `EXECUTOR_REPORT.01-06.md` и `TASK_ACCEPTANCE.01-06.md`.
