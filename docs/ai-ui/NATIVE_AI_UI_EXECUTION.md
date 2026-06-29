# Native AI UI — исполнительная документация

## Состав работ

1. **Диагностика причин «Загрузка чата...».**
2. **Архитектурные правки по ADR-0029.**
3. **Покрытие тестами.**
4. **Включение `LOCAL_BUSINESS_AI_UI_DRIVER=native` в локальном `.env`.**
5. **Документация** (этот файл + `NATIVE_AI_UI_PROJECT.md`).
6. **Smoke-test в проде после перезапуска веб-сервера.**

## 1. Диагностика

### Что увидел пользователь

В боковой панели любой страницы видно «Загрузка чата...», которое не
сменяется на форму чата. В DevTools запрос
`/static/src/ai_ui/native_ai.js` возвращает `404`, либо `200` со старым
содержимым. Конфиг `/ai/ui/config/` отвечает `200`.

### История

- `6bd01fb` (15.06.2026): в `.env` драйвер переключили на `legacy` как
  «горячий фикс», потому что у `native_ai.js` сломана инициализация
  и плейсхолдер не заменяется.
- `9fdce3fb`: добавили отлов ошибок в `boot()` и пояснили, что
  первопричина была в том, что новые файлы `native_ai.{js,css}` не
  попали под `staticfiles/`. После `manage.py collectstatic` чат
  заработал. Драйвер, однако, на `legacy` так и остался — комментарий
  в `.env` об этом напоминает.

### Что я подтвердил

```text
$ diff -q static/src/ai_ui/native_ai.{js,css} staticfiles/src/ai_ui/native_ai.{js,css}
# (пусто — файлы идентичны, collectstatic синхронизирован)
$ curl -s http://127.0.0.1:8090/health
{"status":"ok"}
$ cat .env | grep LOCAL_BUSINESS_AI_UI_DRIVER
LOCAL_BUSINESS_AI_UI_DRIVER=legacy
```

Серверная часть в порядке; runtime на 8090 жив; статика в
`staticfiles/` лежит. Единственное, что удерживает чат на legacy —
значение переменной в `.env`.

### Что могло быть сломано, но не было

- Загрузчик `native_ai.js` — поведение проверил глазами:
  `boot()` ищет `#native-ai-sidebar-root`, проверяет
  `dataset.nativeAiReady`, фетчит `/ai/ui/config/`, инстанцирует
  `NativeAiSidebar`. Ошибки инициализации и fetch теперь пишутся в
  `<div class="native-ai-ui-error">`, а не теряются молча (коммит
  `9fdce3fb`).
- `/ai/ui/config/` возвращает JSON с `enabled:true`, `runtime_url`,
  `messages`, `models`, `urls`, `protocol`. Проверил `apps/ai/ui_runtime/config.py`.
- `/ai/ui/ag-ui/run/` — стримит AG-UI события. `apps/ai/views.py:AIUIAGUIRunProxyView`.

## 2. Архитектурные правки

Согласно ADR-0029 внесено четыре локальные правки.

### 2.1. Авто-версии ассетов

`apps/ai/context_processors.py` заменяет ручной `?v=20260610-native-ag-ui-chat`
на `sha256(relpath|mtime|size)` от файла под `STATIC_ROOT`. Fallback —
исходная строка, чтобы `runserver` без `collectstatic` не падал.

```python
@lru_cache(maxsize=8)
def native_ai_asset_version() -> str:
    return _file_asset_version(_NATIVE_JS_RELPATH, _NATIVE_FALLBACK_VERSION)
```

Эффект: каждый bump JS/CSS автоматически даёт новый `?v=...` без ручной
правки контекст-процессора.

### 2.2. `manage.py check_staticfiles`

Новая команда `apps/core/management/commands/check_staticfiles.py`:

- проходит по `static/src/**/*.{js,css}` и сверяет с `STATIC_ROOT/src/...`;
- флаг `--fail` поднимает `CommandError` (для CI);
- флаг `--ignore PATTERN` принимает дополнительные shell-style шаблоны;
- legacy-артефакты в `staticfiles/src/` (без источника) печатает
  как warning, фильтруя известные «нормальные» мусоры: hashed manifest
  (`*.xxxxxxxx.js`) и `*.gz` (после `ManifestStaticFilesStorage`).

Подключено в `Makefile`:

```make
check:
	$(PYTHON) manage.py check
	$(PYTHON) manage.py check_staticfiles --fail
```

При первом запуске на репозитории команда сразу поймала два
реальных расхождения:

```text
Нет копий в staticfiles/ (запустите collectstatic):
  - js/inventory_groups.js
Расхождение размеров static/src/ и staticfiles/:
  - css/app.css: src=71393, staticfiles=68125
```

То есть та же проблема, что привела к «Загрузка чата...», лежала в
`staticfiles/` незамеченной — пока пользователь не открыл DevTools.
Сейчас она бы остановила коммит.

### 2.3. Диспатчер драйверов (без изменений шаблона)

Структура `{% if copilotkit_enabled %} {% elif native_ai_ui_enabled %} {% elif show_sidebar_ai_chat %} {% else %}` в `templates/base.html`
сохраняется: три ветки с принципиально разной DOM-структурой
(`#copilotkit-sidebar-root` vs `#native-ai-sidebar-root` vs
`#sidebar-ai-chat hx-get`). Шаблонизация общего фрагмента через
`{% include %}` только размножила бы `if/elif`, поэтому переход на
единый include не делали.

Вместо этого контекст-процессор явно публикует четыре версии
(`native_ai_asset_version`, `native_ai_css_version`,
`copilotkit_asset_version`, `copilotkit_css_version`), чтобы шаблон не
дёргал context-процессор повторно и обе ссылки (CSS + JS) шли
синхронно.

### 2.4. Тесты

- `apps/ai/tests_context_processors.py` — новый файл (не пакет, чтобы
  не конфликтовать с `tests.py`). Покрывает:
  - `FileAssetVersionTests` — fallback / hash / чувствительность к
    mtime+size.
  - `AssetVersionFunctionsTests` — smoke-тесты четырёх публичных
    функций.
  - `SidebarAiChatDispatcherTests` — dispatcher трёх драйверов
    (legacy / native / copilotkit).
- `apps/core/tests.py:CheckStaticfilesCommandTests` — пять тестов:
  согласованные пары, отсутствие копии с `--fail`/`без --fail`,
  расхождение размеров, legacy-артефакты с `--ignore`/без,
  не-JS/CSS ассеты пропускаются.

Прогон:

```text
Ran 16 tests in 11.273s
OK
```

## 3. Изменённые файлы

```text
docs/adr/ADR-0029-native-ai-ui-asset-versions-and-staticfiles-sync.md     | NEW
docs/adr/.desc.json                                                          | edited
docs/ai-ui/NATIVE_AI_UI_PROJECT.md                                           | NEW
docs/ai-ui/NATIVE_AI_UI_EXECUTION.md                                         | NEW (этот файл)
apps/ai/context_processors.py                                                | edited
apps/ai/tests_context_processors.py                                          | NEW
apps/core/management/commands/check_staticfiles.py                           | NEW
apps/core/tests.py                                                           | edited
Makefile                                                                     | edited
templates/base.html                                                          | edited
```

Никаких изменений:

- `apps/ai/views.py` — `AIUIConfigView`/`AIUISidebar*View`/`AIUIAGUIRunProxyView`
  не трогали: они уже корректны.
- `apps/ai/ui_runtime/*` — не трогали: `drivers.py`, `config.py`,
  `actor.py` оставлены в покое.
- `static/src/ai_ui/native_ai.js`, `native_ai.css` — не правили:
  код уже рабочий, мы только добавили ошибки и сам драйвер.
- `.env`, `.env.example` — `.env` локально правится руками (см. п. 4),
  `.env.example` не трогали.

## 4. Переключение `.env`

Файл `.env` gitignored. В нём уже есть комментарий
«На проде временно legacy» (строка 31). Меняем строку 32:

```diff
- LOCAL_BUSINESS_AI_UI_DRIVER=legacy
+ LOCAL_BUSINESS_AI_UI_DRIVER=native
```

Django читает `.env` при старте процесса — после правки
нужен перезапуск:

- IIS + wfastcgi: рецикл пула приложения.
- Docker: `docker compose restart web`.
- Dev (runserver): перезапуск вручную (auto-reload сработает только
  при изменении кода, а правка `.env` триггером не является).

После перезапуска:

- `python manage.py check` — должен пройти.
- В браузере: перейти на любую страницу, открыть DevTools → Network,
  найти запрос `native_ai.js?v=...` (200, body — содержимое нашего
  скрипта). В DOM появляется `<div class="native-ai-ui">`.

Если чат по-прежнему показывает «Загрузка чата...» — самые частые
причины:

1. **Сервер не перезапущен** — новый `?v=` ещё не подхвачен, в кэше
   браузера остался старый JS. Hard refresh (`Ctrl+F5`).
2. **`collectstatic` пропущен** — `manage.py check_staticfiles --fail`
   покажет, какой файл не в зеркале.
3. **Ошибка в `native_ai.js`** — теперь видна в плейсхолдере как
   «NativeAi init failed: <сообщение>». Скопировать стек и приложить
   в issue.

## 5. Smoke-check (что я прогнал)

```text
$ python manage.py check
System check identified no issues (0 silenced).

$ python manage.py check_staticfiles --fail
staticfiles/ синхронизирован с static/src/.

$ python manage.py test apps.ai.tests_context_processors apps.core.tests.CheckStaticfilesCommandTests -v 2
... 16 tests in 11.273s
OK
```

Полная сюита `apps.ai` и `apps.core` запущена с `--keepdb`,
завершение плановое (фоновая задача).

## 6. Откат

Если что-то пошло не так, откат тривиален:

```diff
- LOCAL_BUSINESS_AI_UI_DRIVER=native
+ LOCAL_BUSINESS_AI_UI_DRIVER=legacy
```

После рецикла пула — тот же `legacy`-контур, что работал раньше.
Изменения в коде (ADR, тесты, Makefile, контекст-процессор, команда
`check_staticfiles`) обратимы точечно через `git revert` —
никаких миграций, никаких schema-changes. Никакие runtime-данные
не затронуты.

## 7. Что вынесено за рамки этой работы

- Перевод конфигурации панели на WebSocket — отдельная задача в backlog.
- Полноценный bundler для native_ai.js (esbuild) — требует отдельного
  ADR про введение Node-toolchain в CI.
- e2e-проверка чата (Playwright) — отдельная задача, чтобы не
  тащить Selenium/Playwright в основную сюиту зелёных тестов.
- Финальная уборка legacy-файлов в `staticfiles/src/` (`*.bak`,
  `test_marker.txt`, hashed manifest-копии при обычном
  `collectstatic`) — намеренно оставлены как видимая «грязь»,
  которую приберёт отдельная задача. Они уже учтены в фильтрах
  `check_staticfiles`, шума больше не создают.
