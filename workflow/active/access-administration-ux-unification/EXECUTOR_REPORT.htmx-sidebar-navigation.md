# Исполнительский отчёт: HTMX-навигация боковых панелей

## Реализовано

- Добавлены постоянные регионы `#access-field-sidebar-host`, `#access-inspector-host` и `#access-table-panel`.
- ИИ-чат вынесен в отдельный `#access-ai-chat-host`; при открытии редактора он только скрывается и не заменяется HTMX.
- Большой экран разделён на partials таблицы, левого редактора и правого инспектора.
- Ссылки имени, ячеек, статуса, полей инспектора и закрытия используют progressive-enhancement HTMX с `hx-target`, `hx-swap` и `hx-push-url`; обычные ссылки и POST остаются резервным полным HTTP-потоком.
- HTMX GET возвращает только разрешённый fragment. Неизвестный `HX-Target` отклоняется ответом 400.
- Preview и ошибки обновляют только активную панель. Успешный HTMX apply возвращает свежую активную панель и OOB-обновление `#access-table-panel`; обычный apply сохраняет 302.
- После HTMX swap/history restore повторно применяются dirty guard, inert, focus и скрытие AI-контейнера. Во время запроса target получает `aria-busy`.
- `HX-Target` нормализуется из реального значения без `#` (совместим и с вариантом с префиксом); неизвестная цель получает 400.
- Preview/apply не изменяют URL через `hx-push-url`; preview помечает форму как dirty, а apply выводит и однократно потребляет inline-сообщение.
- После закрытия восстанавливается фокус на исходной строке; открытие панели переводит фокус внутрь, а preview-замена формы его не сбрасывает. Busy-состояние очищается также при ошибке HTMX.
- AI-чат помечен `hx-preserve`; browser-проверка сравнивает строгую идентичность узла после открытия, Back и Forward.
- HTMX history-restore без `HX-Target` возвращает полный shell, чтобы cache miss не превращался в ошибку 400.
- При сетевой ошибке редактор не заменяется ответом ошибки, dirty-маркер восстанавливается, а закрытие снова требует подтверждения.

## Проверки

- `make verify-fast TEST_SCOPE=apps/settings_center/tests.py` — `64 passed, 1 deselected, 9 subtests passed`.
- `node --check static/src/js/access_workspace.js` — успешно.
- `git diff --check` — успешно.
- targeted Django HTMX tests (включая history-restore) — `3 passed`.
- `./node_modules/.bin/playwright test --config scripts/e2e/playwright.config.ts scripts/e2e/tests/access_administration.spec.ts` с `E2E_BASE_URL=http://127.0.0.1:8005` — `10 passed`.
- Браузерная проверка выполнена на отдельном порту с актуальной копией `.local/e2e-smoke-6owV7b/e2e.sqlite3`; сервер на 8004 не изменялся.

## Остаточные риски

- Переключатели вкладок и фильтры намеренно остаются обычной полной навигацией согласно non-goal пакета.
- После успешного apply HTMX сообщение выводится в активной панели и потребляется из очереди Django messages; обычный full GET не повторяет его.
