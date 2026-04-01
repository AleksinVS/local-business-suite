# Block Brief

## Block

Добавить в проект новое Django-приложение `waiting_list` для записи пациентов в очередь на исследования и одновременно перевести уже реализованные серверные экраны на общий визуальный язык из `drafts/waiting_list.html`.

## Proposed Direction

- Сохранить текущий стек: Django Templates, HTMX и общий `static/src/css/app.css`, без отдельного frontend bundler.
- Вынести визуальные примитивы из `drafts/waiting_list.html` в общий layout и shared CSS, затем применить их к существующим экранам.
- Реализовать `apps/waiting_list` как отдельное Django app с repo-convention PK: обычный int/`BigAutoField`, без UUID primary key.
- Если в ходе реализации появится реальная потребность в неугадываемом внешнем идентификаторе, использовать отдельное поле `external_id = UUIDField(...)`, не меняя первичный ключ.
- Держать `service_id` как bounded string field с локальным choice-каталогом в приложении, а не вводить отдельную таблицу услуг в этом блоке.
- Оставить доступ bounded: `LoginRequired` для экрана и действий без новой role/policy matrix.
- Для внешних CLI runtime bindings использовать только корректные launcher/model combinations; оркестратор должен запускать такие worker-ы через `$cli-subagents` wrappers, а не raw shell invocation.

## Why This Block

Сейчас в проекте есть рабочие Django-приложения, но нового продуктового модуля waiting list нет, а визуальная система уже существующих экранов отличается от нового референса. Этот блок закрывает оба разрыва в пределах текущего server-rendered стека.

## Risks

- Общий restyle через `base.html` и `app.css` может затронуть существующие HTMX-паттерны и тестовые ожидания.
- Новый модуль с миграцией, partials и drawer-UX затрагивает schema, routes, templates и progressive enhancement одновременно.
- Маски ввода и keyboard shortcuts легко сделать хрупкими, если они начнут конфликтовать с обычными формами и браузерным поведением.
- Грязное рабочее дерево требует жёсткого соблюдения file scope, чтобы не задеть посторонние изменения.

## Open Questions

- Открытых продуктовых решений перед началом исполнения нет.
- Для этого блока уже согласованы bounded simplifications: `service_id` остаётся локальным catalog field, а доступ ограничивается authenticated-only flow.

## User Decision Needed

Дополнительное решение пользователя перед исполнением не требуется.
