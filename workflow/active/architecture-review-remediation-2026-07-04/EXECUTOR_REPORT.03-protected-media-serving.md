# Executor report: 03-protected-media-serving

Дата: 2026-07-07
Исполнитель: Claude agent (executor)
Пакет: `workflow/active/architecture-review-remediation-2026-07-04/task-packets/03-protected-media-serving.json`
Риск: high (security/privacy — раздача пользовательских файлов)

## Что сделано

Вложения заявок (`WorkOrderAttachment.file`, `data/media/workorders/...`) больше не
раздаются через `static(settings.MEDIA_URL, ...)`. Вместо этого добавлен
авторизованный view, который работает одинаково в dev и production.

### 1. View выдачи файла — `apps/workorders/views.py`

Функция `serve_workorder_attachment(request, path)` с декоратором `@login_required`:

- **Резолв через доменный объект.** Относительный путь из URL превращается в
  `workorders/<path>` и сопоставляется с полем `WorkOrderAttachment.file`
  (`get_object_or_404(WorkOrderAttachment, file=relative_name)`). Из найденного
  вложения берётся заявка, право её видеть проверяется штатной политикой
  `can_view(request.user, attachment.workorder)` — не изобретаем свою проверку.
- **Отказ = 404, а не 403.** Пользователю без доступа отдаём `Http404`, чтобы не
  раскрывать сам факт существования файла. Это тот же приём, что в
  `WorkOrderDetailView` (там outsider получает 404 через visible-queryset).
- **Защита от path traversal.** Абсолютный путь строится строго от `MEDIA_ROOT`
  (`(media_root / "workorders" / path).resolve()`) и обязан лежать внутри
  `MEDIA_ROOT.resolve()`: проверка `is_relative_to(media_root)`. Любой выход за
  пределы (`../../`, ведущий слэш, абсолютный путь) → 404. Проверка стоит **до**
  обращения к БД и файловой системе.
- **Стриминг.** Отдаём `FileResponse(open("rb"), filename=...)` — потоковая
  выдача, крупные файлы не читаются в память целиком. Content-Type берётся из
  сохранённого `attachment.content_type`, если он задан (иначе `FileResponse`
  угадывает по имени файла).
- Если запись в БД есть, но файла на диске нет — 404.

### 2. Маршрут — `config/urls.py`

- Удалён `static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` (и его
  импорт `from django.conf.urls.static import static`).
- Добавлен `re_path(r"^media/workorders/(?P<path>.*)$", serve_workorder_attachment,
  name="workorder_attachment")`. URL специально сохранён как `/media/workorders/...`,
  чтобы совпадать с тем, что возвращает `attachment.file.url` — шаблоны
  (`templates/workorders/partials/attachments.html`, вне write_scope) продолжают
  работать без изменений.

Почему маршрут в `config/urls.py`, а не в `apps/workorders/urls.py`: `MEDIA_URL`
— это верхнеуровневый префикс `/media/`, а `apps/workorders/urls.py` подключён под
`/workorders/`. Роут, объявленный там, получил бы URL `/workorders/media/...` и не
совпал бы с `file.url`. Логика (view) при этом живёт в домене (`apps/workorders/views.py`),
а `config/urls.py` только связывает верхнеуровневый префикс с этой view — так же,
как он уже импортирует `PortalLoginView` и `service_worker`.

### 3. Документация

- `docs/deployment/DEPLOYMENT.md` — подраздел в блоке Caddy: `/media/` раздаёт
  только Django; reverse proxy не должен отдавать `/media/` как статику напрямую.
- `docs/deployment/IIS_SSO.md` — подраздел «`/media/` обслуживает только Django, не
  IIS»: не создавать static-обработчик/virtual directory для `/media/`; handler
  mapping `path="*"` из примера `web.config` уже покрывает `/media/...`.

## Изменённые файлы

- `apps/workorders/views.py` — view `serve_workorder_attachment` + импорты
  (`Path`, `settings`, `login_required`, `FileResponse`, `Http404`, `can_view`).
- `config/urls.py` — снят `static(MEDIA_URL, ...)`, добавлен защищённый маршрут.
- `apps/workorders/tests.py` — класс `WorkOrderAttachmentServingTests` (4 теста).
- `docs/deployment/DEPLOYMENT.md`, `docs/deployment/IIS_SSO.md` — правила про `/media/`.

`apps/workorders/policies.py` и `apps/core/` не менялись — существующей `can_view`
достаточно, отдельный helper не потребовался.

## Тесты

Новый класс `WorkOrderAttachmentServingTests` (`@override_settings(MEDIA_ROOT=tempfile.mkdtemp())`,
временный каталог чистится в `tearDownClass`, реальный `data/media/` не трогается):

- `test_anonymous_is_redirected_to_login` — аноним → 302 на `/accounts/login/`.
- `test_outsider_without_access_gets_404` — аутентифицированный без доступа → 404.
- `test_user_with_access_receives_file_with_content_type` — заказчик заявки → 200,
  `Content-Type: image/jpeg`, тело файла совпадает с загруженным (через
  `streaming_content`).
- `test_path_traversal_attempt_returns_404` — секрет за пределами `MEDIA_ROOT`,
  запрос `/media/workorders/../../wo_secret.txt` → 404, содержимое не утекает.

## Acceptance checks — фактический вывод

**1. `.venv/bin/python manage.py test apps.workorders.tests`**

```
Ran 67 tests in 428.931s

OK
```

(63 существовавших теста + 4 новых. В логе виден `PermissionDenied`/`Forbidden` —
это существующие тесты `test_customer_cannot_drag_card_to_technical_column` и
`test_technician_cannot_rate_closed_workorder`, которые намеренно проверяют 403;
общий результат — `OK`.)

**2. `grep -n "static(settings.MEDIA_URL" config/urls.py` — вхождений нет**

```
$ grep -n "static(settings.MEDIA_URL" config/urls.py
$ echo $?
1
```

(exit code 1 = совпадений нет, как и требуется.)

**3. `.venv/bin/python manage.py check`**

```
System check identified no issues (0 silenced).
```

## Методологическая заметка (backend/DevSecOps)

**Почему авторизованная выдача через view правильнее раздачи статикой.**
`static(settings.MEDIA_URL, ...)` — это dev-хелпер Django: он подключает маршрут
только при `DEBUG=1` и отдаёт файл напрямую с диска, не зная ничего про
пользователя и его права. Отсюда два дефекта разом: (а) при `DEBUG=0` маршрут
исчезает — в production вложения давали 404; (б) в dev любой, кто знает/угадал URL,
скачивал чужой файл заявки без входа в систему. Файл — это такой же ресурс, как
страница заявки: доступ к нему должен проходить ту же авторизацию. View решает обе
проблемы: он есть в любом окружении (маршрут не зависит от `DEBUG`) и перед отдачей
байтов выполняет `login_required` + доменную проверку `can_view`. Отдача идёт через
`FileResponse` — потоково, поэтому даже крупные файлы не грузят память процесса.
Общий принцип: раздача статики через веб-сервер/`static()` годится только для
публичных, неконфиденциальных ресурсов; всё, что зависит от прав, обязано идти
через приложение.

**Как устроена защита от traversal.** Опасность: клиент присылает в пути `../` (или
ведущий слэш / абсолютный путь), пытаясь выйти из каталога media и прочитать
произвольный файл сервера (`/etc/passwd`, `.env`, БД). Мы никогда не доверяем строке
пути напрямую. Путь склеивается от доверенного корня `MEDIA_ROOT`, затем
`Path.resolve()` схлопывает все `..` и симлинки в один канонический абсолютный путь,
и проверяется `resolve().is_relative_to(MEDIA_ROOT.resolve())`. Если после
нормализации путь оказался вне `MEDIA_ROOT` — это выход за границу, отдаём 404 и до
чтения файла не доходим. Ключевой момент — сравнивать **уже разрешённые** пути:
проверять исходную строку на подстроку `..` ненадёжно (кодировки, симлинки),
а канонизация через `resolve()` устойчива.

## Известные ограничения и кандидаты в backlog

- **`apps.ai.ChatAttachment` (`chat_attachments/%Y/%m/%d/`).** В проекте есть второй
  тип media — вложения AI-чата, которые раздавались тем же снятым
  `static(MEDIA_URL, ...)` и используются в `templates/ai/chat_detail.html`
  (`att.file.url`). Мой маршрут покрывает только `/media/workorders/`, поэтому
  `/media/chat_attachments/...` теперь не обслуживается. Важно: в production
  (`DEBUG=0`) они и раньше давали 404 — новой production-регрессии нет; регрессия
  только в dev, где раньше файлы отдавались (без проверки прав — то есть это была та
  же уязвимость). `apps/ai/` вне write_scope этого пакета и вне non-goals, поэтому не
  трогал. **Кандидат в backlog:** аналогичный защищённый view для `ChatAttachment`
  с проверкой прав на чат, а лучше — единый media-dispatcher по префиксу с
  per-domain политикой (эта развилка уже отмечена в `implementation_notes` пакета).
- **X-Accel-Redirect / X-Sendfile.** Сейчас файл стримит сам Django (`FileResponse`).
  Для больших файлов/высокой нагрузки это можно отдать reverse proxy: view проверяет
  права и возвращает заголовок `X-Accel-Redirect` (nginx) / `X-Sendfile`, а раздачу
  байтов делает proxy из `internal`-локации. Это оптимизация производительности, не
  безопасности; отложена, зафиксирована здесь как кандидат в backlog.

## Не сделано намеренно (по non-goals пакета)

- Модель `WorkOrderAttachment` не менялась.
- S3/объектное хранилище не вводилось.
- Шаблоны не менялись (URL `/media/workorders/...` сохранён, `file.url` работает).

Коммит/push не делал — по инструкции пакета коммитит оркестратор после приёмки.
