# Приёмка: 03-protected-media-serving

Дата: 2026-07-07.
Роли: исполнитель — субагент (Opus); независимая проверка — отдельный субагент
(Opus, состязательная); hardening по замечанию + приёмка — агент-оркестратор.

## Вердикт

**Принят с доработкой оркестратора.** Независимый верификатор вынес
ACCEPT-WITH-NOTES (не REWORK); единственный реальный дефект (null-байт → 500)
устранён оркестратором сразу, с тестом.

## Что проверено

Исполнение (executor report + независимая проверка):

- Вложения заявок раздаёт авторизованный view `serve_workorder_attachment`
  (`apps/workorders/views.py`, `@login_required`) в любом окружении; из
  `config/urls.py` снят `static(settings.MEDIA_URL, ...)`, добавлен
  `re_path(r"^media/workorders/(?P<path>.*)$", ...)` — URL совпадает с
  `attachment.file.url`, шаблоны работают без правок.
- **Авторизация привязана к доменному объекту:** относительный путь из URL
  сопоставляется с `WorkOrderAttachment.file` (точное совпадение строки),
  из вложения берётся заявка, право проверяется штатной `can_view` — тот же
  гейт, что у `WorkOrderDetailView`. Отказ = 404 (не 403), не раскрывает факт
  существования файла.
- **Traversal доказанно не пробивается** (независимая состязательная проверка):
  голый `../../`, URL-кодированные `%2e%2e%2f` / `..%2f`, ведущий слэш,
  абсолютный путь, кросс-доменный `../chat_attachments/` — все дают 404, утечки
  файла нет. Настоящий якорь защиты — exact-match DB-lookup по литеральной
  строке `workorders/<path>` + `can_view`; guard `is_relative_to(MEDIA_ROOT)` —
  defense-in-depth.
- **FileResponse корректен:** `Content-Disposition: inline; filename=...`
  (картинки показываются inline, принудительной скачки нет), стриминг для
  крупных файлов, ручной `Content-Type` из `attachment.content_type`.
- Правило «/media/ раздаёт только Django, не IIS/reverse-proxy» добавлено в
  `docs/deployment/DEPLOYMENT.md` и `docs/deployment/IIS_SSO.md`.
- Scope соблюдён: изменены ровно 5 файлов из `write_scope`; `policies.py` и
  `apps/core/` не тронуты (существующей `can_view` хватило).

## Acceptance-проверки

- `.venv/bin/python manage.py test apps.workorders.tests` → **Ran 70 tests, OK**
  (67 исходных + 3 добавленных оркестратором).
- `grep -n "static(settings.MEDIA_URL" config/urls.py` → пусто (exit 1).
- `.venv/bin/python manage.py check` → без ошибок.

## Доработка оркестратора (по замечанию верификатора)

Верификатор нашёл один реальный дефект устойчивости: `path` с null-байтом
(`\x00`) ломал `Path.resolve()` (`ValueError: embedded null byte`), не
перехватывался → **HTTP 500 вместо 404**. Низкая важность (аноним не доходит —
302; утечки файла нет; реальные Caddy/gunicorn обычно режут `%00` раньше), но
Django сам его не фильтрует.

Оркестратор внёс hardening в `serve_workorder_attachment`: в начале view
`if "\x00" in path: raise Http404(...)` — до `resolve()`. Добавлены 3 теста в
`WorkOrderAttachmentServingTests` (закрывают пробелы покрытия, отмеченные
верификатором):
- `test_null_byte_in_path_returns_404_not_500` — регрессия на сам дефект;
- `test_url_encoded_traversal_attempt_returns_404` — `%2e%2e%2f` / `..%2f`;
- `test_missing_file_on_disk_returns_404` — запись есть, файла нет → 404, не 500.

## Замечания и отложенные пункты

1. **Регрессия `apps.ai.ChatAttachment` (dev-only, вынесено в backlog).**
   `ChatAttachment` (`/media/chat_attachments/...`, шаблон
   `templates/ai/chat_detail.html`) раздавался тем же снятым `static()`. В prod
   (`DEBUG=0`, подтверждён `deployments/test-host/.env`) он и раньше давал 404 —
   **новой прод-регрессии нет**; в dev теперь тоже 404 (раньше — без проверки
   прав, та же уязвимость). `apps/ai/` вне write_scope. Нужен аналогичный
   защищённый view для чата или единый media-dispatcher по префиксу — занесено
   в `docs/planning/backlog.md` (раздел Next), требует решения владельца по
   приоритету (кандидат в отдельный пакет 13).
2. **`SECURE_CONTENT_TYPE_NOSNIFF` не задан** (defense-in-depth): файлы отдаются
   inline с клиентски-заявленным типом. Практический риск низкий
   (`ATTACHMENT_ALLOWED_TYPES` — картинки/PDF/Office/`text/plain`, без html/svg),
   поведение pre-existing (старый `static()` был таким же). Кандидат: глобально
   `SECURE_CONTENT_TYPE_NOSNIFF=True` и/или `Content-Disposition: attachment`
   для не-картинок — отдельным решением (затрагивает settings, вне scope).
3. E2e-тест из пакета (п.5, «DEBUG=0-эквивалентная конфигурация») не реализован;
   функционально не критичен — view не зависит от `DEBUG`, что и есть суть фикса,
   и это покрыто unit-тестами на все ветки.

## Гигиена коммита

На момент приёмки в рабочем дереве присутствовали файлы параллельного пакета 08
(`apps/core/contract_drift.py` и др.) — пакет 03 закоммичен **явным pathspec**
из своих файлов, чтобы не примешать чужую работу.
