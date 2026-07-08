# Executor report: 09-legacy-ai-ui-driver-removal

Дата: 2026-07-07
Исполнитель: Claude agent (executor)
Пакет: `workflow/archive/2026/architecture-review-remediation-2026-07-04/task-packets/09-legacy-ai-ui-driver-removal.json`
ADR: `docs/adr/ADR-0032-retire-legacy-ai-ui-driver.md` (Accepted)

## Инвентаризация (до удаления)

`grep -rn "legacy\|DRIVER_LEGACY"` по `apps/ai`, `templates/ai`, `static/src`, `scripts/e2e`,
`docs`, `.env*` дал два непересекающихся класса находок:

1. **Настоящие UI-driver-legacy места** (подлежат удалению/правке):
   - `apps/ai/ui_runtime/drivers.py` — `DRIVER_LEGACY`, `VALID_AI_UI_DRIVERS`, фолбэки;
   - `apps/ai/ui_runtime/__init__.py` — упоминание "legacy sidebar" в docstring;
   - `config/settings.py` — валидация `LOCAL_BUSINESS_AI_UI_DRIVER`;
   - `apps/ai/tests_context_processors.py` — `test_legacy_driver_disables_both_native_and_copilotkit`
     и импорт `DRIVER_LEGACY`;
   - `scripts/e2e/tests/native_ai_ui.spec.ts`, `copilotkit_sidebar.spec.ts` — дефолтное
     значение `aiUiDriver` при отсутствии `E2E_AI_UI_DRIVER`;
   - `scripts/e2e/tests/sidebar_ai_context.spec.ts` — весь файл целиком гейтился
     на `aiUiDriver === "legacy"`;
   - `.env.example` — дублирующая активная строка `LOCAL_BUSINESS_AI_UI_DRIVER=legacy`
     (побеждала строку `=native` выше по файлу) и её описание;
   - `docs/guides/AI_UI_PROTOCOL_OPERATIONS.md`, `docs/deployment/AI_UI_PROTOCOL_DEPLOYMENT.md`,
     `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`, `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md` —
     упоминания `legacy` как рабочего режима/rollback-опции;
   - `.desc.json` записи, ссылающиеся на матрицу `legacy/copilotkit/native`.

2. **Не-UI-driver legacy** (НЕ трогал, per явный запрет и здравый смысл):
   - `apps/ai/management/commands/migrate_legacy_chat_db.py` — legacy = архивная SQLite
     chat-БД, не UI-драйвер (только что менялся пакетом 10, не трогал);
   - `README.md` (4 упоминания), `docs/deployment/DEPLOYMENT.md` (2 упоминания) — все про
     legacy/dev SQLite и docker-контейнеры, не про AI UI. Изменений не вносил;
   - `apps/ai/tests.py:112` `test_legacy_copilotkit_flag_still_enables_copilotkit_when_driver_is_implicit` —
     тест старого флага `LOCAL_BUSINESS_COPILOTKIT_ENABLED`, не про значение `legacy`;
   - `apps/ai/tests.py:~1757` — комментарий "legacy client" про обратную совместимость memory API;
   - `docs/architecture/*.md` (AI_UI_PROTOCOL_FOUNDATION_PLAN.md и т.д.) — исторические
     планы соответствующих ADR, оставлены как есть (аналогично ADR — фиксируют, что было
     решено на момент написания);
   - `docs/adr/*` (кроме ADR-0028, отдельно уточнённого) — исторические записи.

## Функциональная находка за пределами текстового "legacy" (ловушка №2)

В `templates/ai/` и `static/src/` слова "legacy" действительно нет, но по функции нашёл
старый HTMX sidebar-чат — предшественник protocol foundation (ADR-0019, 2026-05-28),
который ADR-0032 явно требует убрать ("шаблоны, статика, view-ветки и тесты, используемые
только legacy-драйвером"):

- `apps/ai/views.py`: `AISidebarChatView`, `AISidebarChatClearView` — не имели вообще
  никакой проверки драйвера в dispatch, но рендерились только в третьей `{% elif %}`-ветке
  `templates/base.html`, которая срабатывала, только когда `ai_ui_driver` не равен ни
  `copilotkit`, ни `native` — то есть именно в состоянии, которое раньше называлось `legacy`;
- `templates/ai/partials/sidebar_chat.html` — единственный файл в этой директории;
  `templates/ai/.desc.json` описывал `partials/` как "включая встроенный sidebar-чат";
- `static/src/js/sidebar_chat.js` — JS только для `#sidebar-ai-chat`;
- `templates/base.html` — третья `{% elif show_sidebar_ai_chat %}` ветка и безусловный
  `<script src=".../sidebar_chat.js">`;
- `apps/ai/context_processors.py`: `show_sidebar_ai_chat` — контекстный флаг, чьё
  единственное назначение прямым текстом подтверждено комментарием в
  `tests_context_processors.py` ("контейнер для HTMX-чата").

Решающий аргумент был не "похоже на legacy", а строгое доказательство мёртвого кода:
после того как `config/settings.py` перестал допускать `LOCAL_BUSINESS_AI_UI_DRIVER=legacy`
(падает при старте), `configured_ai_ui_driver()` математически не может вернуть ничего,
кроме `copilotkit`/`native`, для аутентифицированного пользователя — третья ветка в
`base.html` стала недостижимой навсегда, при любой корректной конфигурации. Удалять
такой код — не расширение скоупа "на всякий случай", а прямое следствие ADR-0032.

Это решение вышло за пределы буквально перечисленных write_scope путей (`apps/ai/urls.py`
и `templates/base.html` не были в списке) — детали ниже, в разделе "Дополнения к write_scope".

## Изменённые файлы

### Код
- `config/settings.py` — извлечена `_validate_ai_ui_driver()`; допустимые значения
  `{copilotkit, native}`; `legacy` даёт отдельный явный текст ошибки про переход на `native`
  (ADR-0032), прочие некорректные значения — общий текст. Функция вынесена отдельно, чтобы
  быть unit-тестируемой без перезагрузки модуля settings (что небезопасно — settings.py
  читается один раз при старте процесса).
- `apps/ai/ui_runtime/drivers.py` — убран `DRIVER_LEGACY`; `VALID_AI_UI_DRIVERS = {copilotkit, native}`;
  фолбэки `normalize_ai_ui_driver()` (для нераспознанного значения) и
  `authenticated_ai_ui_driver()` (для неаутентифицированного пользователя) — оба на `native`
  вместо `legacy`.
- `apps/ai/ui_runtime/__init__.py` — docstring без упоминания "legacy sidebar".
- `apps/ai/context_processors.py` — убран мёртвый ключ `show_sidebar_ai_chat`.
- `apps/ai/views.py` — удалены `AISidebarChatView`, `AISidebarChatClearView`.
- `apps/ai/urls.py` *(не в исходном write_scope — правка неизбежна вместе с views.py)* —
  убраны роуты `chat/sidebar/` (`sidebar_chat`) и `chat/sidebar/clear/` (`sidebar_chat_clear`)
  и соответствующие импорты.
- `templates/base.html` *(не в исходном write_scope)* — убрана третья `{% elif show_sidebar_ai_chat %}`
  ветка и безусловный `<script src="{% static 'src/js/sidebar_chat.js' %}">`. Без этой правки
  удаление `sidebar_chat.js` было бы небезопасно: в production `STORAGES.staticfiles` —
  `whitenoise.storage.CompressedManifestStaticFilesStorage`, и `{% static %}` на
  отсутствующий в манифесте файл рушит рендер **каждой** страницы (`base.html` used site-wide).

### Шаблоны/статика (write_scope: `templates/ai/`, `static/src/js/`)
- `templates/ai/partials/sidebar_chat.html` — удалён (каталог `partials/` стал пустым, удалён).
- `static/src/js/sidebar_chat.js` — удалён.
- `templates/ai/.desc.json`, `static/src/.desc.json` — записи удалены.

### Тесты
- `apps/ai/tests.py` — удалены `test_sidebar_chat_clear_deletes_sidebar_messages_and_summary`
  и `test_sidebar_chat_hides_tool_messages` (тестировали только удалённые view). Проверено, что
  покрытие не потеряно: `test_native_ai_ui_clear_session_returns_clean_config` уже проверяет
  тот же сервисный путь (`clear_sidebar_session`: очистка сообщений, сохранение `model_id`,
  снятие `sidebar_summary`) через `AIUISidebarSessionClearView` (native/copilotkit-нейтральный
  эндпоинт). `test_sidebar_summary_skips_tool_messages` (юнит на `_build_sidebar_summary_text`,
  без обращения к view) — оставлен без изменений.
- `apps/ai/tests_context_processors.py` (авторизовано оркестратором) — убран импорт
  `DRIVER_LEGACY`; `test_legacy_driver_disables_both_native_and_copilotkit` заменён на
  `test_legacy_ai_ui_driver_raises_improperly_configured_with_native_hint`, который вызывает
  `config.settings._validate_ai_ui_driver("legacy")` напрямую и проверяет `ImproperlyConfigured`
  с упоминанием `legacy` и `native` в тексте; убраны мёртвые ассерты `ctx["show_sidebar_ai_chat"]`
  из трёх оставшихся тестов.

### E2E (write_scope: `scripts/e2e/tests/`)
- `scripts/e2e/tests/sidebar_ai_context.spec.ts` — удалён целиком: весь файл был
  `test.skip(aiUiDriver !== "legacy", ...)`, а `legacy` больше не достижим ни при какой
  корректной конфигурации Django (падает при старте) — файл был обречён оставаться
  вечно skip. Общий механизм page-context tracking, который он частично проверял
  (`LocalBusinessPageContext`, `/ai/context/window/`), остаётся покрыт
  `right_panel_ai_navigation.spec.ts` и частично `native_ai_ui.spec.ts`
  (`forwardedProps.page_context`); специфичный сценарий "трекинг контекста на доске заявок
  через левую панель" такого покрытия больше не имеет — отмечаю как возможный follow-up,
  не восстанавливал его сам (вне цели этой задачи).
- `scripts/e2e/tests/native_ai_ui.spec.ts` — дефолт `E2E_AI_UI_DRIVER` изменён `"legacy"` → `"native"`.
- `scripts/e2e/tests/copilotkit_sidebar.spec.ts` — дефолт в тернарнике изменён `"legacy"` → `"native"`.
- `scripts/e2e/tests/.desc.json` — запись про `sidebar_ai_context.spec.ts` удалена.

### Документация
- `.env.example` — убрана дублирующая строка `LOCAL_BUSINESS_AI_UI_DRIVER=legacy` (строка 52,
  побеждала `=native` по правилам dotenv); комментарий переписан под `native`/`copilotkit`
  и явно фиксирует, что `legacy` роняет Django.
- `docs/guides/AI_UI_PROTOCOL_OPERATIONS.md` (write_scope) — матрица, статус, секции
  "Проверка режимов", e2e-команды и Rollback приведены к `copilotkit/native`.
- `docs/deployment/AI_UI_PROTOCOL_DEPLOYMENT.md`, `docs/deployment/COPILOTKIT_AG_UI_DEPLOYMENT.md`
  (write_scope: `docs/deployment/`) — убраны разделы/строки про процесс `legacy` и rollback
  на `legacy`.
- `docs/deployment/.desc.json`, `docs/guides/.desc.json` — записи про матрицу
  `legacy/copilotkit/native` исправлены на `copilotkit/native`.
- `docs/adr/ADR-0028-versioned-ai-ui-protocol-foundation.md` (write_scope) — в блок "Статус"
  добавлено примечание, что матрица уточнена ADR-0032 до `copilotkit|native`; исторический
  текст решения от 2026-06-09 не переписывал (сохранена точность истории).
- `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md` *(не в исходном write_scope)* — два места
  советовали `LOCAL_BUSINESS_AI_UI_DRIVER=legacy` как "аварийный откат"/"быстрый rollback".
  Это реальный эксплуатационный риск (в точности повторяет инцидент 2026-06-15, упомянутый
  в implementation_notes): дежурный, следуя гайду, уронил бы Django. Заменил на `native`.
- `README.md` — проверил все 4 вхождения "legacy": все про SQLite/data store, к AI UI
  driver не относятся (уже описывает `native` как дефолт и `copilotkit` как pilot без
  упоминания `legacy`). Изменений не вносил.

## Дополнения к write_scope (за рамками исходного JSON-пакета)

1. `apps/ai/urls.py` — механически неизбежно вместе с удалением view-классов из
   `apps/ai/views.py` (иначе `ImportError` при старте).
2. `templates/base.html` — без этого удаление `sidebar_chat.js`/`sidebar_chat.html` было бы
   небезопасно (см. обоснование про `CompressedManifestStaticFilesStorage` выше); шаблон
   используется на каждой странице сайта.
3. `docs/guides/COPILOTKIT_AG_UI_OPERATIONS.md` — операционный риск (runbook советовал
   ронять прод), решил исправить, а не оставлять как "историческое упоминание".

Не тронул (оставил как есть, при сомнении в скоупе — не удалял):
- `docs/guides/AI_SIDEBAR_CHAT.md` (ADR-0019) — в основном описывает общую, не
  legacy-специфичную инфраструктуру (page context envelope, `ui.open_right_panel`,
  module AI skills, chat_settings contract), которая используется всеми драйверами.
  Последняя строка документа ссылается на удалённый `sidebar_ai_context.spec.ts` —
  осталась битая ссылка. Файл не входит в write_scope (только
  `AI_UI_PROTOCOL_OPERATIONS.md` явно указан), а основной контент документа не про
  legacy-driver, поэтому переписывать его не стал — фиксирую как документационный долг
  для отдельного follow-up.
- `docs/planning/backlog.md` и `docs/architecture/*.md` — исторические/чужие блоки
  (native-ag-ui-chat-development, memory-alignment и т.д.) с фразами вроде "проверить
  legacy, copilotkit, native smoke" — не мой write_scope, оставил их владельцам этих
  блоков.
- `PROJECT_STRUCTURE.yaml` — не регенерировал (`make gen-struct` — задача оркестратора),
  но все затронутые `.desc.json` обновлены, так что регенерация подтянет актуальные описания.

## Методзаметка (для владельца)

Тройной драйвер (legacy/copilotkit/native) утраивал не только код выбора драйвера, но и
каждый слой над ним: шаблон, JS, url-роут, unit-тест, e2e-сценарий и строку в
операционных гайдах — на каждый добавленный драйвер работы становится не +1, а +N по
числу таких слоёв. Здесь это подтвердилось буквально: `legacy` тянул за собой отдельный
view, отдельный шаблон, отдельный JS-файл, отдельную e2e-сущность и упоминания в шести
документах, при том что сам драйвер не получал регулярных прогонов (не было e2e-джоба,
который держал бы его живым) — то есть "страховка" на практике была необнаруживаемо
сломана уже давно и создавала ложное чувство защиты. Инцидент 2026-06-15 (production
временно переключали на `legacy` как обход поломки native-статики) — пример того, чем
это опасно: путь, который никто не проверяет, оказывается единственным, что спасает
прод в момент паники, и никто не знает, действительно ли он работает.

`ImproperlyConfigured` вместо тихого fallback — сознательный выбор fail-fast над
fail-safe для конфигурации (в отличие от runtime-ошибок в бизнес-логике, где иногда
уместен graceful degradation). Тихий fallback здесь означал бы: кто-то ставит
`LOCAL_BUSINESS_AI_UI_DRIVER=legacy`, ожидая rollback-поведения, а получает молча
работающий `native` (или раньше — молча работающий `legacy`, о существовании кода
которого никто не помнит) — то есть система "работает", но не то, что попросили,
и это вскрывается не сразу, а в проде под нагрузкой. Явный отказ при старте процесса
(а не при первом HTTP-запросе) — самая ранняя точка, где можно поймать ошибку
конфигурации, до того как она затронула пользователей.

## Проверки

```
.venv/bin/python manage.py test apps.ai.tests apps.ai.tests_context_processors
# Ran 109 tests in 164.710s — OK

.venv/bin/python manage.py test apps.ai
# Ran 109 tests in 178.786s — OK (полный apps.ai, включая оба test-модуля)

.venv/bin/python manage.py check
# System check identified no issues (0 silenced).

.venv/bin/python manage.py makemigrations --check --dry-run
# No changes detected

.venv/bin/python manage.py validate_architecture_contracts
# 17 контрактов: 10 совпадает с дефолтом, 7 "рабочая копия изменена (ожидаемо)" — как и до правки

LOCAL_BUSINESS_AI_UI_DRIVER=legacy .venv/bin/python manage.py check
# ImproperlyConfigured: "LOCAL_BUSINESS_AI_UI_DRIVER=legacy больше не поддерживается: ...
#  замените её на LOCAL_BUSINESS_AI_UI_DRIVER=native (режим по умолчанию) либо =copilotkit."

reverse("ai:sidebar_chat") -> NoReverseMatch (подтверждено вручную через django.urls.reverse)
```

### grep-проверка (acceptance)

```
grep -rn "DRIVER_LEGACY\|=legacy\|\"legacy\"\|'legacy'" apps/ai config/settings.py .env.example
```

Остались только:
- `apps/ai/management/commands/migrate_legacy_chat_db.py` — SQLite chat-БД, не UI-driver
  (явно исключено заданием);
- `config/settings.py`, `.env.example`, `apps/ai/tests_context_processors.py` — сама
  проверка/тест отказа `legacy` и комментарий, объясняющий, что драйвер выведен.

Других вхождений "легаси-как-рабочего-значения" не осталось.

### E2E

Playwright (`npx playwright test --list ... native_ai_ui.spec.ts`) подтвердил, что файл
синтаксически валиден и содержит 2 теста после правки. Полный прогон
(`npx playwright test scripts/e2e/tests/native_ai_ui.spec.ts`) **не выполнялся** — в этом
окружении нет поднятого Django-сервера на `127.0.0.1:8001` и не заданы
`E2E_USERNAME`/`E2E_PASSWORD` (для этого нужен отдельный `runserver` + тестовый
пользователь). Браузер Chromium для Playwright в окружении установлен. Основание для
приёмки на этом уровне — unit-тесты (109/109 OK), `manage.py check`, ручная проверка
`ImproperlyConfigured` и grep, как и допускает задание при недоступности e2e-окружения.

## Итог

- Матрица драйверов AI UI: `{copilotkit, native}`, `native` — дефолт.
- `LOCAL_BUSINESS_AI_UI_DRIVER=legacy` падает при старте Django с понятным сообщением
  про переход на `native`.
- Legacy-driver код (view/url/template/JS/context-flag) убран как доказанно мёртвый код,
  не только как "текстовое совпадение".
- Юнит-тесты и `manage.py check` зелёные; e2e не запускался (нет сервера/браузерного
  окружения с учётными данными) — см. раздел выше.
