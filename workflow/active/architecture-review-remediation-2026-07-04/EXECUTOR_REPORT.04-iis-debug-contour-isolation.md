# Executor Report: 04-iis-debug-contour-isolation

Дата: 2026-07-07.
Пакет: `workflow/active/architecture-review-remediation-2026-07-04/task-packets/04-iis-debug-contour-isolation.json`

## Что сделано

### 1. Флаг `LOCAL_BUSINESS_IIS_COMPAT_ENABLED` (`config/settings.py`, default `false`)

- `TRUE_VALUES`/`env_bool(...)` перенесены выше по файлу (сразу после блока
  `DJANGO_ENV`), чтобы флагом можно было пользоваться уже при сборке `MIDDLEWARE`
  (раньше `env_bool` был определён ниже места, где раньше был жёстко прописан
  список `MIDDLEWARE`). Само определение не менялось, только позиция в файле.
- `LOCAL_BUSINESS_IIS_COMPAT_ENABLED = env_bool("LOCAL_BUSINESS_IIS_COMPAT_ENABLED", False)`.
- `MIDDLEWARE` теперь собирается функцией `build_middleware(iis_compat_enabled)`:
  при `False` список **не содержит** `apps.core.middleware.PathInfoDebugMiddleware`
  вообще (не просто «middleware выключен внутри себя» — записи в списке нет).
  Вынесение в функцию сделано специально по указанию постановки: `MIDDLEWARE`
  собирается один раз при импорте settings, поэтому тест на «middleware
  отсутствует» не может полагаться на runtime `override_settings(...)`; вместо
  этого тест вызывает `build_middleware(False)`/`build_middleware(True)` напрямую
  и проверяет условие сборки.
- `apps/core/urls.py`: `debug_request` регистрируется только при
  `settings.DEBUG and settings.LOCAL_BUSINESS_IIS_COMPAT_ENABLED` (было — только
  `settings.DEBUG`).

### 2. Лог PATH_INFO-фикса — через штатный `logging`, не `open()` (`apps/core/middleware.py`)

- Убраны: жёстко зашитый путь `C:\inetpub\portal\debug_path.log`, `open(..., "a")`
  внутри `__call__`, `try/except Exception: pass` (молчаливое поглощение ошибок),
  импорт `datetime`/`os` (оба стали не нужны).
- Middleware пишет `logger.info(...)` в логгер `apps.core.iis_path_debug`
  (лениво, через `%s`-плейсхолдеры, а не f-string, чтобы не тратить время на
  форматирование, если запись всё равно будет отфильтрована по уровню).
- Сама эвристика исправления `PATH_INFO`/`SCRIPT_NAME`/`request.path`/`request.path_info`
  **не менялась** (non-goal пакета) — байт-в-байт то же условие и присваивания,
  что и раньше.

### 3. Логирование в `config/settings.py` (`LOGGING`)

- Новый handler `iis_path_debug_file`: `RotatingFileHandler` на
  `DATA_DIR / "logs" / "iis_path_debug.log"` (5 МБ x 3 бэкапа), **`delay=True`** —
  файл не создаётся на диске, пока не случится хотя бы одна реально прошедшая
  через уровень логгера запись.
- Новый логгер `apps.core.iis_path_debug`: `propagate=False` (не дублируется в
  `app.log`/консоль, как и раньше лог шёл только в свой файл), уровень —
  `LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL` (env, default `WARNING`).
- Итоговая связка: middleware пишет на уровне `INFO`; логгер по умолчанию
  `WARNING` → в дефолтной конфигурации (даже при включённом
  `LOCAL_BUSINESS_IIS_COMPAT_ENABLED`) ничего не пишется и файл не создаётся.
  Подробный лог включается **отдельно от флага деплоя**, уровнем логгера
  (`LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL=INFO`) — это разделение специально
  выбрано так, чтобы для диагностики PATH_INFO не требовалось включать
  `DJANGO_DEBUG=1` на проде (полный DEBUG даёт трейсбеки и другую чувствительную
  информацию — отдельная, более широкая поверхность риска, чем один
  диагностический лог).

### 4. Документация

- `docs/deployment/IIS_SSO.md`: раздел «Флаг `LOCAL_BUSINESS_IIS_COMPAT_ENABLED`
  (обязателен на IIS)» — что выключено по умолчанию и почему, что включить на
  IIS; раздел «Отладка» переписан под новую логгер-based схему с примером
  `LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL=INFO`; пример `web.config` дополнен
  `<add key="LOCAL_BUSINESS_IIS_COMPAT_ENABLED" value="true" />`.
- `.env.example`: закомментированные примеры
  `LOCAL_BUSINESS_IIS_COMPAT_ENABLED=true` и
  `LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL=INFO` с пояснением.

### 5. Мусорный файл в корне рабочей копии

Удалён: `rm 'C:\inetpub\portal\debug_path.log'` (797 КБ, буквальное имя файла с
`:`/`\` — создавался построчным `open()` в `apps/core/middleware.py`, т.к.
Linux не трактует `\`/`:` как разделители пути). Файл не был в git (уже
подпадал под `*.gitignore` правило `*.log`, что подтверждено
`git check-ignore -v`) — правка `.gitignore` не потребовалась.

### 6. Побочный однострочный фикс — `apps/core/debug_views.py`

Строка `f"Script Name: {request.script_name}"` обращалась к несуществующему
атрибуту (`WSGIRequest` не имеет `.script_name`) — `AttributeError` при
реальном обращении к view. Баг предсуществующий, никогда не был покрыт
тестами (grep подтвердил: `debug_request` не встречался в тестах вообще).
Всплыл, когда я написал позитивный тест «`debug_request` возвращает 200 при
включённом флаге и DEBUG» (сверх минимального требования пакета — 404 при
выключенном). Заменил на `request.META.get('SCRIPT_NAME', '')`, как и в
остальных местах того же view. Файл в write_scope пакета; логику вывода
(дамп environ) не менял — это вне цели пакета 04, только gating.

## Тесты (`apps/core/tests.py`, класс `IisCompatContourTests`, 9 тестов)

| Требование пакета | Тест |
| --- | --- |
| Выключенный флаг: middleware отсутствует в `MIDDLEWARE` (условие сборки, не только runtime) | `test_middleware_excluded_from_build_when_flag_disabled` (`build_middleware(False)`) |
| Включённый флаг: middleware присутствует | `test_middleware_included_in_build_when_flag_enabled` (`build_middleware(True)`) |
| Выключенный флаг: запрос не создаёт файлов | `test_request_with_flag_disabled_creates_no_files` (реальный HTTP-запрос через `self.client` с `override_settings(MIDDLEWARE=build_middleware(False))`; проверены и легаси Windows-путь, и новый `iis_path_debug.log`) |
| Включённый флаг: PATH_INFO-фикс работает как раньше | `test_path_info_fix_rewrites_mismatched_request_uri_when_enabled`, `test_path_info_fix_skips_favicon_and_static_when_enabled` (написаны и прогнаны на исходном коде **до** правки логирования в middleware — сама эвристика не менялась, тесты остались зелёными после рефакторинга без единой правки) |
| `debug_request` → 404 при выключенном флаге | `test_debug_request_is_404_when_flag_disabled` (`DEBUG=True`, флаг `False`) |
| Регрессия: лог идёт через `logging`, не `open()` | `test_middleware_logs_via_standard_logging_not_open` (`assertLogs` на логгер `apps.core.iis_path_debug`; плюс проверка отсутствия легаси Windows-пути) |
| Доп. (сверх минимума): `debug_request` реально отдаёт 200 при флаге+DEBUG включённых | `test_debug_request_is_registered_when_flag_and_debug_enabled` |
| Доп.: `debug_request` → 404 при `DEBUG=False`, даже если флаг включён | `test_debug_request_is_404_when_debug_disabled_even_if_flag_enabled` |

Технический момент: `apps/core/urls.py` строит `urlpatterns` один раз при
импорте модуля, а вложенный `include("apps.core.urls")` в `config/urls.py`
кэширует построенный список ещё и на уровне `URLResolver.url_patterns`
(`cached_property` конкретного объекта-резолвера, который переживает
`clear_url_caches()`). Поэтому тесты на 404/200 через реальный HTTP-клиент
используют хелпер `_reload_core_urls()`: `importlib.reload()` и
`apps/core/urls.py`, и `config/urls.py`, затем `clear_url_caches()` —
только так `override_settings(...)` реально долетает до резолвера в тесте
(проверено эмпирически: без перезагрузки `config.urls` тест падал с
`NoReverseMatch`, хотя `build_middleware`/значение флага были верны).

## Команды проверок и фактические результаты

1. `.venv/bin/python manage.py test apps.core.tests`

   ```
   Ran 71 tests in ~40s
   OK
   ```

2. `.venv/bin/python manage.py check`

   ```
   System check identified no issues (0 silenced).
   ```

3. `ls 'C:\inetpub\portal\debug_path.log'`

   ```
   ls: cannot access 'C:\inetpub\portal\debug_path.log': No such file or directory
   ```

4. Точечная регрессия за пределами `apps.core` (MIDDLEWARE/urls — общие для
   всего проекта файлы): `apps.accounts.tests apps.workorders.tests
   apps.settings_center.tests apps.notifications.tests` — см. ниже (фактический
   вывод дописан после завершения фонового прогона).

## Отклонения от буквальной постановки

- Добавлен побочный однострочный фикс в `apps/core/debug_views.py`
  (`request.script_name` → `request.META.get('SCRIPT_NAME', '')`) — вне
  прямой формулировки задачи, но в пределах write_scope, обнаружен
  собственным тестом, минимальный риск (см. п.6 выше).
- Написаны 2 дополнительных теста сверх минимально требуемых пакетом
  (проверка 200-ответа `debug_request` при включённом флаге и 404 при
  `DEBUG=False`) — для более полного покрытия обеих осей условия
  (`DEBUG and IIS_COMPAT_ENABLED`), не только описанной в пакете ветки.
- Подробность лога управляется исключительно уровнем логгера
  (`LOCAL_BUSINESS_IIS_PATH_DEBUG_LOG_LEVEL`), отдельный второй env-флаг
  (`LOCAL_BUSINESS_IIS_PATH_DEBUG_ENABLED` или подобный) не заводился —
  постановка явно оставляла выбор между «отдельным флагом» и «уровнем
  логгера» на усмотрение исполнителя.

## Координация с параллельным пакетом 05

В рабочей копии присутствуют несохранённые изменения в `apps/ai/tests.py` и
`services/agent_runtime/tests/test_normalization.py` (не мои — параллельный
исполнитель пакета `05-ai-gateway-mcp-identity-reverification`, чей
executor report уже появился в этой же директории). Эти файлы и каталоги
(`apps/ai/`, `services/agent_runtime/`) не трогал, как и предписано в задаче.

## Файлы, изменённые пакетом 04

- `apps/core/middleware.py`
- `apps/core/debug_views.py`
- `apps/core/urls.py`
- `config/settings.py`
- `apps/core/tests.py`
- `docs/deployment/IIS_SSO.md`
- `.env.example`
- Удалён (не в git): `C:\inetpub\portal\debug_path.log`

`make gen-struct` не запускался (по инструкции — регенерирует оркестратор при
приёмке); новых файлов пакет не создавал, `.desc.json` не менялся.

Не коммитил (по инструкции пакета).
