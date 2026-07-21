# План: контекстный ИИ-чат в левой боковой панели

Статус: implemented, awaiting owner acceptance.

Дата: 2026-05-28.

Связанный ADR: `docs/adr/ADR-0019-context-aware-sidebar-ai-chat.md`.

Workflow: `workflow/archive/2026/context-aware-sidebar-ai-chat/`.

## Фактический результат MVP

Реализовано 2026-05-28:

- меню левой панели перенесено в выпадающий список `Все функции`;
- левая панель показывает встроенный ИИ-чат и использует отдельную `sidebar`-сессию;
- полная страница чата продолжает работать и может открыть sidebar-сессию по ссылке из панели;
- на странице `AI чат` левый сайдбар показывает список чат-сессий вместо второго встроенного ИИ-чата, а центральная часть целиком занята текущим диалогом;
- добавлен общий runtime contract `contracts/ai/chat_settings.json` и descriptor Settings Center `ai.contract.chat_settings`;
- добавлены `PageContextEnvelope`, browser bridge `static/src/js/page_context.js`, endpoint обновления window context и краткоживущая модель `AIWindowContextSnapshot`;
- сообщение чата привязывается к конкретному `context_snapshot_id`, а `ui.get_current_context` читает bound snapshot, а не latest snapshot окна;
- детальная server-side резолюция selection реализована для `workorders`;
- для остальных маршрутов публикуется базовый контекст `module/view`; детальные selection-resolvers для inventory, waiting_list, memory review и analytics остаются расширениями по модульным сценариям;
- sidebar-сессия компактируется через `ChatSession.metadata.sidebar_summary`, последние сообщения берутся из `surfaces.sidebar.recent_message_limit`, по умолчанию `8`;
- добавлен Playwright e2e для сценария `login -> workorders board -> sidebar chat -> open workorder drawer -> context snapshot`.

Ограничения MVP:

- e2e проверяет доступность контекста карточки и заполнение `window_id/context_version`, но не вызывает реальный LLM для формулировки ответа;
- race-safety покрыта серверной привязкой snapshot в unit-тестах, а не отдельным браузерным тестом с реальным runtime;
- полноценный event bus/event store не вводится;
- UI просмотра/ручной перегенерации summary не реализуется по принятому решению.

## Цель

Сделать ИИ-чат постоянным рабочим помощником в левой боковой панели, а навигацию перенести в выпадающее меню `Все функции` в верхнем левом блоке. Чат должен понимать текущий экран, модуль, фильтры и выбранный объект, например открытую карточку заявки в правой панели.

## Пользовательская ценность

- Пользователь не покидает доску, карточку, аналитику или ревью памяти ради вопроса к ИИ.
- Можно писать `что с этой заявкой?`, `добавь комментарий`, `найди похожие случаи`, и бот понимает текущую карточку.
- Одна chat-система работает и в отдельной странице, и во встроенном режиме; sidebar-режим использует отдельную рабочую сессию.

## Non-goals первого среза

- Не делать полноценную универсальную платформу событий.
- Не хранить каждый UI-event как журнал пользовательской активности.
- Не делать real-time синхронизацию между несколькими окнами.
- Не передавать в ИИ полный HTML страницы или сырые данные карточек.
- Не менять доменную модель заявок, памяти или аналитики ради UI-контекста.

## Архитектурное решение

Первый срез использует `PageContextEnvelope`.

Источник контекста:

- серверные шаблоны добавляют `data-ai-context` на страницу, список, карточку, drawer или рабочую область;
- JS bridge собирает самый конкретный активный контекст;
- HTMX swaps вызывают обновление контекста;
- JS bridge публикует sanitized envelope на сервер как снимок окна;
- встроенный чат отправляет `window_id`, `context_version` и короткий `context_hint`;
- ИИ-бот вызывает `ui.get_current_context`, когда ответ зависит от текущего окна.

Сервер:

- валидирует envelope;
- проверяет права пользователя;
- резолвит выбранный объект заново через selector/source adapter;
- хранит краткоживущий snapshot текущего окна;
- дает agent runtime read-only tool `ui.get_current_context`;
- сохраняет краткий audit/digest в metadata сообщения.

## Почему не event platform сейчас

Полноценная event platform нужна, когда события должны жить дольше текущего пользовательского действия и иметь нескольких подписчиков:

- memory ingestion;
- analytics facts;
- audit;
- уведомления;
- автоматизации;
- real-time обновления.

Текущий сценарий проще: чату нужен актуальный снимок состояния экрана на момент отправки сообщения. Поэтому вводим совместимый по форме envelope, но без очереди, persistent event store и подписчиков.

Расширение позже:

- `PageContextEnvelope` можно превратить в `EventEnvelope`;
- `ai-context:update` можно публиковать в общий event bus;
- server-side доменные события можно подключить к памяти и аналитике без изменения UI-контракта.

## `ui.get_current_context` как отдельный инструмент

Имеет смысл ввести отдельный read-only инструмент `ui.get_current_context`.

Но его не должен "вызывать ИИ один раз при переходе пользователя на страницу": при переходе страницы ИИ-бот не выполняется сам по себе. Переход происходит в браузере. Поэтому правильная схема такая:

1. Браузер при загрузке страницы, HTMX-swap, открытии/закрытии drawer и смене фильтров отправляет текущий `PageContextEnvelope` на backend.
2. Backend сохраняет snapshot по `window_id` и увеличивает `context_version`.
3. Sidebar chat при отправке сообщения передает `window_id`, `context_version` и короткий `context_hint`.
4. Backend привязывает к `ChatMessage` конкретный `context_snapshot_id`.
5. Agent runtime получает инструкцию: если ответ зависит от текущего окна, вызвать `ui.get_current_context`.
6. Tool возвращает серверно проверенный safe summary snapshot, привязанный к текущему сообщению/запросу, а не latest context окна.

Плюсы:

- меньше данных в каждом промте;
- ниже риск случайной передачи лишнего видимого текста;
- context можно резолвить и проверять на сервере;
- бот получает контекст только тогда, когда он реально нужен;
- можно отследить устаревший `context_version`.
- можно защититься от гонки: пользователь отправил вопрос по заявке A и сразу открыл заявку B.

Минусы:

- нужен небольшой server-side storage для snapshot окна;
- нужен новый инструмент и prompt rule;
- если browser не отправил обновление после HTMX-swap, tool вернет старый snapshot.

Решение: использовать `ui.get_current_context` в MVP, но не вводить event bus/event store.

## UX-решение

### Верхний левый блок

Содержит:

- кнопку `Все функции`;
- выпадающее меню со всеми текущими пунктами левой навигации;
- избранные функции остаются в верхней панели.

Поведение:

- меню открывается по клику;
- закрывается по клику вне меню и по `Esc`;
- доступно с клавиатуры;
- видимость пунктов сохраняет текущие `show_*_nav` условия;
- logout остается доступным в меню.

### Левая боковая панель

Содержит компактный ИИ-чат:

- заголовок `ИИ-помощник`;
- текущая модель;
- последние сообщения отдельной sidebar-сессии;
- поле ввода;
- кнопка отправки;
- ссылка `Открыть полный чат`;
- индикатор текущего контекста: `Доска / Заявка 123` или `Аналитика / Дашборд`.
- управление режимом панели: `Закрепить` / `Свернуть`.

Компактный режим может не показывать:

- список всех сессий;
- расширенное меню команд;
- крупные превью вложений.

Sidebar chat использует отдельную `sidebar`-сессию пользователя. Полная страница чата может открыть эту сессию по ссылке `Открыть полный чат`, но обычные full-page сессии не смешиваются с sidebar-сессией автоматически.

Если пользователь открыл несколько вкладок, все они могут писать в одну sidebar-сессию. Это допустимо только при условии, что каждое сообщение хранит свой `window_id/context_snapshot_id/context_hint`, а summary сохраняет смену контекста между сообщениями.

Встроенный режим на рабочих страницах не содержит переключатель сессий. Под переключателем понимался компактный selector для выбора другой chat-сессии прямо в сайдбаре. Для MVP это не нужно: сайдбар показывает только текущую sidebar-сессию, а история и выбор других диалогов остаются на полной странице чата. На самой странице `AI чат` левый сайдбар является списком чат-сессий, а не встроенным sidebar-чатом.

### Режимы левой панели

Панель поддерживает:

- `pinned`: закреплена, занимает штатную ширину и видна постоянно;
- `collapsed`: свернута до узкой кнопки/иконки, основной экран получает больше места;
- временное раскрытие поверх контента на мобильном viewport.

Состояние хранится в `localStorage` и не является бизнес-настройкой. Сервер не должен зависеть от того, свернута панель или нет.

### Суммаризация sidebar-диалога

Цель: sidebar-сессия должна оставаться короткой и рабочей, не накапливая бесконечную историю.

Правило:

- последние `N` сообщений остаются как обычная история;
- `N` берется из эффективных настроек `ai.chat_settings` для поверхности `sidebar`, по умолчанию `8`;
- настройка валидируется как integer, рекомендуемые границы `4..50`;
- более старые сообщения суммаризуются в `ChatSession.metadata.sidebar_summary`;
- хранить `summarized_from_message_id`, `summarized_until_message_id`, `source_message_ids`, `summary_version`, `summary_updated_at`;
- prompt runtime получает `sidebar_summary` плюс последние `N` сообщений;
- compact запускается после нового сообщения, если несуммаризованный хвост больше порога;
- дополнительно browser может вызвать compact через `navigator.sendBeacon` на `pagehide`, но этот механизм best-effort и не должен быть единственным.

Если runtime недоступен, compact откладывается. Чат продолжает работать с расширенным хвостом до следующей успешной попытки.

Отдельный UI для просмотра или ручной перегенерации summary в MVP не нужен. Summary считается внутренним runtime state; для диагностики достаточно metadata/admin/trace.

`sidebar_summary` считается чувствительным runtime state:

- не отправлять summary в память автоматически;
- не писать raw summary в обычные audit payload/logs;
- доступ к summary только по тем же правилам, что к `ChatSession`;
- перед сохранением применять masking/safety pass;
- хранить provenance через диапазон/source message ids.

### Общий runtime contract настроек чата

Настройки основного ИИ-чата и sidebar-чата должны храниться в общем контракте `ai.chat_settings`, а не в отдельных разрозненных параметрах. Общие лимиты и режимы задаются в `defaults`, различия поверхностей - в `surfaces.full_page` и `surfaces.sidebar`.

Планируемые файлы:

- default contract: `contracts/ai/chat_settings.json`;
- runtime override: `data/contracts/ai/chat_settings.json`;
- Settings Center descriptor: `ai.contract.chat_settings`;
- loader/helper: `get_chat_settings(surface="full_page" | "sidebar")`.

Начальный контракт:

```json
{
  "schema_version": "1",
  "defaults": {
    "recent_message_limit": 20,
    "summary_enabled": true,
    "summary_trigger_messages": 24,
    "max_prompt_chars": 10000,
    "context_tool_enabled": true
  },
  "surfaces": {
    "full_page": {
      "recent_message_limit": 20,
      "summary_enabled": false
    },
    "sidebar": {
      "recent_message_limit": 8,
      "summary_enabled": true,
      "session_mode": "dedicated",
      "session_switcher": false
    }
  }
}
```

Правило разрешения: runtime сначала читает `defaults`, затем накладывает overrides из `surfaces.<surface>`. Итоговые настройки валидируются типами и диапазонами до использования в prompt runtime и UI.

Общие параметры, которые должны жить в одном контракте:

- лимит последних сообщений;
- включение и порог суммаризации;
- максимальный размер prompt/input;
- доступность `ui.get_current_context`;
- позже: лимиты вложений, подробность trace/audit, timeout/retry.

Surface-specific параметры:

- `sidebar.session_mode=dedicated`;
- `sidebar.recent_message_limit=8`;
- `sidebar.session_switcher=false`;
- `full_page.summary_enabled=false` для MVP, чтобы не менять поведение основной страницы без отдельного решения.

`pinned/collapsed` состояние левой панели не входит в runtime contract. Это локальное состояние браузера и хранится в `localStorage`.

## Контракт контекста

Минимальный envelope:

```json
{
  "schema_version": "1",
  "window_id": "browser-tab-uuid",
  "context_version": 42,
  "page": {
    "path": "/workorders/",
    "title": "Канбан заявок",
    "module": "workorders",
    "view": "board"
  },
  "selection": {
    "object_type": "workorder",
    "object_id": "123",
    "source_code": "workorders",
    "display": "123. Заменить кабель"
  },
  "filters": {},
  "ui_state": {},
  "capabilities": {}
}
```

Правила:

- `schema_version` обязателен;
- `window_id` обязателен для sidebar chat и создается браузером на вкладку;
- `context_version` увеличивается backend при каждом принятом обновлении snapshot;
- `page.module` должен быть из allow-list зарегистрированных модулей;
- `selection.object_id` передается строкой, сервер сам нормализует тип;
- клиентский `display` нужен только для UI и не является доверенным источником;
- `capabilities` из клиента используются только как UI-hint и всегда пересчитываются сервером;
- поля вне схемы отбрасываются;
- максимальный размер envelope ограничить, ориентир 8-16 KB.

## Хранилище window context

MVP-хранилище: модель `AIWindowContextSnapshot` в `apps.ai`.

Поля:

- `user`;
- `window_id`;
- `context_version`;
- `context_hash`;
- `sanitized_envelope`;
- `resolved_summary`;
- `is_current`;
- `created_at`;
- `updated_at`;
- `expires_at`.

Индексы/ограничения:

- unique `(user, window_id, context_version)`;
- index `(user, window_id, is_current)`;
- index `(expires_at)`.

Поведение:

- context update создает новую immutable row только если изменился `context_hash`;
- предыдущая current row для `user/window_id` снимается с `is_current`;
- submit сообщения ищет row по `user/window_id/context_version`;
- если row не найдена, сообщение получает `context_stale/context_unavailable`, а backend не подменяет ее latest row;
- `ChatMessage.metadata` хранит `context_snapshot_id`, `window_id`, `context_version`, `context_hash`, `context_hint` и safe summary;
- `ui.get_current_context` читает bound snapshot текущего message/request;
- cleanup command/job удаляет rows с `expires_at < now`.

Endpoint обновления контекста:

- требует обычную session auth и CSRF;
- принимает только allow-list поля;
- имеет max payload;
- имеет server-side rate limit;
- возвращает `window_id`, `context_version`, `context_hash` и краткий `context_hint`.

Browser bridge:

- отправляет snapshot только при изменении hash sanitized envelope;
- использует debounce для фильтров/поиска, ориентир 250-500 ms;
- не читает произвольный видимый текст страницы;
- после HTMX-swap повторно ищет ближайший `data-ai-context`.

## Модульные правила контекста

### Workorders

Страница доски:

- `module=workorders`;
- `view=board`;
- `filters`: текущая доска, подразделение, статус, исполнитель, изделие, поиск;
- при открытии drawer: `selection.object_type=workorder`, `object_id=<pk>`, `source_code=workorders`.

Server resolver:

- использует `visible_workorders_queryset(user)`;
- для action tools применяет существующие `can_*` политики;
- для памяти может использовать `workorders` source adapter.

### Inventory

Первый срез:

- `module=inventory`;
- `view=list/detail`;
- `selection.object_type=device`, если открыт конкретный объект.

### Waiting list

Первый срез:

- `module=waiting_list`;
- `view=dashboard/detail`;
- PII не передается с клиента;
- серверная резолюция должна использовать существующие права и безопасный source adapter.

### Memory review

Первый срез:

- `module=memory`;
- `view=review_dashboard/issue_detail/index_detail`;
- `selection.object_type=memory_issue` или `memory_search_document`;
- бот может объяснить issue, предложить reindex/delete/review action, но write actions идут через confirmation.

### Analytics

Первый срез:

- `module=analytics`;
- `view=dashboard`;
- `filters`: dataset, period, department, drilldown;
- selection может указывать metric/card, если UI ее явно задает.

## Промты и поведение ИИ

В системные подсказки agent runtime добавить правила:

1. Если есть `page_context.selection`, сначала интерпретировать слова `эта заявка`, `эта карточка`, `текущий документ`, `этот issue` как выбранный объект.
2. Если в сообщении есть `window_id/context_version/context_hint`, но нет полного page context, вызвать `ui.get_current_context`, когда ответ зависит от текущего окна.
3. Не доверять клиентскому display как факту. Для фактов использовать доменный tool/get/search.
4. Если пользователь просит изменить объект, использовать write tool только после confirmation flow.
5. Если контекст устарел или объект недоступен, явно сказать, что текущий объект не найден или нет прав.
6. Если контекста нет, работать как обычный чат.

Примеры:

```text
Пользователь: "Что с этой заявкой?"
Контекст: workorders/workorder#123.
Ожидаемо: вызвать workorders.get или workorders.search по workorders, затем ответить по заявке 123.
```

```text
Пользователь: "Добавь комментарий, что ждем инженера."
Контекст: workorders/workorder#123.
Ожидаемо: подготовить workorders.comment с confirmation, не менять данные без подтверждения.
```

## Этапы реализации

### Этап 1. Контракт и серверная подготовка

1. Добавить валидатор `PageContextEnvelope` в `apps.ai` или `apps.core`.
2. Добавить сервис `resolve_page_context(user, envelope)`.
3. Подключить безопасные resolvers для `workorders`, затем расширить на memory/analytics/waiting_list.
4. Добавить `AIWindowContextSnapshot` model/service/migration для server-side snapshot: `window_id`, `user`, `context_version`, `context_hash`, sanitized envelope, resolved summary, `is_current`, timestamps, TTL.
5. Добавить endpoint обновления window context.
6. Добавить cleanup command/job для expired snapshots.
7. Добавить привязку конкретного snapshot к `ChatMessage` при submit.
8. Добавить хранение `context_snapshot_id`, `page_context_digest`, `window_id`, `context_version`, `context_hash` и безопасной краткой сводки в `ChatMessage.metadata`.

Acceptance:

- некорректный envelope отклоняется или очищается;
- чужой `workorder_id` не резолвится;
- client `capabilities` не принимаются как права и пересчитываются сервером;
- контекст не содержит сырых PII/секретов;
- устаревший `context_version` определяется сервером;
- submit сообщения привязывает immutable snapshot и не подменяет его latest context;
- cleanup удаляет expired snapshots.

### Этап 2. Общий JS context bridge

1. Добавить `static/src/js/page_context.js`.
2. Читать `data-ai-context` с `body`, `.page-container`, открытого drawer и активных элементов.
3. Реагировать на `htmx:afterSwap`, `htmx:afterSettle`, клики по карточкам, закрытие drawer.
4. Экспортировать `window.LocalBusinessPageContext.getCurrent()`.
5. Генерировать событие `ai-context:update` для UI-индикатора.
6. Публиковать snapshot на backend и получать `context_version`.
7. Использовать debounce/rate-aware отправку: не чаще изменения hash, debounce 250-500 ms для фильтров/поиска.

Acceptance:

- при открытии карточки в drawer текущий контекст меняется на эту карточку;
- при закрытии drawer selection очищается или возвращается к контексту страницы;
- после HTMX-обновления контекст не теряется;
- chat submit содержит актуальные `window_id` и `context_version`.
- быстрые изменения фильтров не создают лишний поток context update requests.

### Этап 3. Перенос навигации

1. В `templates/base.html` перенести навигацию в dropdown `Все функции`.
2. Сохранить текущие условия видимости пунктов.
3. Оставить избранное в верхней панели.
4. Добавить доступность: `aria-expanded`, `aria-controls`, `Esc`, click outside.
5. Обновить CSS.

Acceptance:

- все текущие пункты меню доступны из `Все функции`;
- keyboard navigation работает;
- logout доступен;
- на мобильном viewport меню не перекрывает основной рабочий сценарий.

### Этап 4. Встроенный ИИ-чат

1. Выделить переиспользуемый partial для chat surface.
2. Поддержать два режима: `full_page` и `sidebar`.
3. Встроить sidebar chat в левую панель на отдельной `sidebar`-сессии.
4. На submit добавлять `window_id`, `context_version`, `context_hint` в POST/stream request.
5. Показывать компактный индикатор текущего контекста.
6. Добавить `pinned/collapsed` режим панели.
7. Добавить суммаризацию sidebar-сессии.
8. Добавить общий `ai.chat_settings` runtime contract с overrides для `full_page` и `sidebar`, по умолчанию `sidebar.recent_message_limit=8`, и descriptor в Settings Center.
9. Добавить safety/masking pass для `sidebar_summary`.

Acceptance:

- сообщение из sidebar попадает в отдельную sidebar-сессию;
- полная страница может открыть sidebar-сессию по ссылке;
- в sidebar рабочих страниц нет переключателя сессий; история диалогов доступна на полной странице;
- на полной странице чата левый sidebar показывает список чат-сессий, не второй ИИ-чат;
- stream работает во встроенном режиме;
- модель выбирается корректно;
- есть ссылка на полный чат;
- compact оставляет последние `N` сообщений и summary старой части;
- `N` берется из `get_chat_settings("sidebar").recent_message_limit` и по умолчанию равен `8`;
- full-page и sidebar chat читают эффективные настройки из одного контракта;
- нет отдельной жестко заданной настройки `sidebar_recent_message_limit`, дублирующей контракт;
- summary хранит source message ids/range и не уходит в память/audit logs автоматически;
- UI просмотра/перегенерации summary не добавляется.

### Этап 5. Интеграция agent runtime

1. Добавить read-only tool `ui.get_current_context`.
2. Передавать `window_id`, `context_version`, `context_hint` и `context_snapshot_id` в `AgentRuntimeClient.chat/chat_stream`.
3. Обновить prompts/tool routing: использовать `ui.get_current_context`, когда ответ зависит от текущего окна.
4. Добавить fallback, если agent runtime не поддерживает новый tool.
5. Обновить trace metadata: `page_context_present`, `context_tool_called`, `module`, `object_type`, `object_id_hash`, `context_version`, `context_snapshot_id`.

Acceptance:

- вопрос `что с этой заявкой?` на открытой карточке приводит к tool call по этой карточке;
- если после submit пользователь открыл другую карточку, текущий запрос использует snapshot исходной карточки;
- `ui.get_current_context` вызывается только для контекст-зависимых запросов;
- без контекста чат работает как раньше;
- write action требует confirmation.

### Этап 6. Проверки и документация

1. Unit tests для envelope validation/resolution.
2. Tests для `AIChatMessageCreateView` и stream path.
3. E2E: открыть доску, открыть карточку, спросить ИИ про текущую карточку.
4. Скриншоты desktop/mobile.
5. Обновить docs/guides после реализации.

Acceptance:

- `python manage.py check`;
- `python manage.py validate_architecture_contracts`;
- `python manage.py test apps.ai.tests apps.workorders.tests`;
- Playwright e2e для sidebar chat context.

## Риски и решения

| Риск | Решение |
| --- | --- |
| Устаревший контекст после HTMX-swap | Единый `page_context.js` и событие `ai-context:update` |
| Клиент подменяет object_id | Серверный resolver и проверка прав |
| Бот отвечает по latest snapshot другой карточки | Привязка immutable `context_snapshot_id` к `ChatMessage` при submit |
| Бот отвечает по устаревшему snapshot | `context_version`, TTL и явное `context_stale/context_unavailable` |
| Сайдбар становится перегруженным | Компактный chat mode и ссылка на полный чат |
| Дублирование chat JS | Выделить общий chat surface API вместо копии кода |
| Утечка PII через DOM | Передавать handles и safe display, не raw fields |
| Sidebar-история становится слишком длинной | Compact после порога + best-effort compact на `pagehide` |
| Несколько вкладок смешивают контекст в одной sidebar-сессии | Хранить `window_id/context_snapshot_id/context_hint` на каждом сообщении и учитывать это в summary |

## Решения перед кодом

Подтверждено:

- sidebar chat использует отдельную sidebar-сессию;
- лимиты истории и суммаризации задаются через общий runtime contract `ai.chat_settings`;
- `surfaces.sidebar.recent_message_limit` по умолчанию равен `8`;
- встроенный режим показывает только текущую sidebar-сессию, без переключателя сессий;
- UI просмотра/ручной перегенерации summary не нужен;
- избранное остается в верхней панели;
- pinned/collapsed режим левой панели нужен.
