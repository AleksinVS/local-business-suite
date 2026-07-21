# ADR-0033: Авто-версии ассетов AI UI и проверка синхронности статики

## Статус

Accepted

## Дата

2026-06-29

## Контекст

Sidebar-чат проекта имеет три драйвера — `legacy` (HTMX + `sidebar_chat.js`),
`native` (самописный JS-клиент `static/src/ai_ui/native_ai.js`,
SSE-стрим через AG-UI), `copilotkit` (React island
`static/dist/copilotkit/copilotkit-island.js`).

В истории эксплуатации уже были два эксплуатационных инцидента, у обоих
одна и та же сигнатура — sidebar показывает «Загрузка чата...» и больше
ничего, в консоли ошибки нет, `/ai/ui/config/` возвращает `200`:

1. Коммит `9fdce3fb` (15 июня) — добавление `static/src/ai_ui/` не было
   подхвачено IIS/WhiteNoise, потому что `collectstatic` после этого никто
   не запустил. Браузер получал `404` на `native_ai.js`, `boot()` не
   вызывался, плейсхолдер оставался навсегда.
2. Коммит `6bd01fb` (тот же день) — до того, как первопричина из пункта 1
   была найдена, драйвер временно переключили на `legacy`. Это
   «костыль», оставленный в `.env` под комментарием «На проде временно
   legacy».

Оба инцидента стали возможны из-за двух системных дефектов:

- **Рассогласование `static/src/` и `staticfiles/` — ручной шаг.**
  Под IIS в проде Django не раздаёт статику сам: `web.config` мапит
  `/static/` напрямую в `staticfiles/`. Если разработчик добавляет файл
  в `static/src/`, dev-сервер его видит (через
  `django.contrib.staticfiles`), прод — нет. Существующая диагностика
  заключается в «открыть DevTools и посмотреть 404», что не масштабируется
  на CI.

- **Asset-версия — магическая строка.** Текущие значения
  `native_ai_asset_version = "20260610-native-ag-ui-chat"` и
  `copilotkit_asset_version = "20260610-copilotkit-page"` хардкодятся
  в `apps/ai/context_processors.py`. Если кто-то меняет содержимое
  `static/src/ai_ui/native_ai.js`, но не подкручивает
  `native_ai_asset_version`, браузер продолжит загружать старый JS из
  кэша и упадёт в ту же «вечную загрузку».

Дополнительно в `staticfiles/src/ai_ui/` обнаружены артефакты
`native_ai.css.bak` и `test_marker.txt`, не имеющие источника под
`static/src/`. Это след ручных правок через `collectstatic --clear +
copy`, выполненных без ревью.

## Решение

### A. Авто-версия ассетов через file hash

В `apps/ai/context_processors.py` заменить хардкод
`native_ai_asset_version` и `copilotkit_asset_version` на отпечаток
`sha256(mtime + size)` соответствующих файлов под `staticfiles/`.
В dev-режиме (если `collectstatic` ещё не запускался) fallback на
прежние магические строки, чтобы не сломать runserver.

Эффект: cache-bust query string `?v=...` меняется автоматически при
каждом изменении JS/CSS. Это устраняет класс регрессов
«обновил код — клиент работает на старом JS».

### B. Команда `manage.py check_staticfiles`

Создать `apps/core/management/commands/check_staticfiles.py`,
которая сравнивает `static/src/**/*.js`, `static/src/**/*.css`
(только эти расширения) с их копиями под `staticfiles/`. Диагностика
в стиле `manage.py validate_architecture_contracts`:

- для каждого источника под `static/src/` проверяется наличие и
  совпадение `size` со staticfiles-копией;
- `--fail` превращает предупреждения в `CommandError` — флаг для CI;
- `--ignore` принимает список шаблонов для legacy-артефактов
  (`native_ai.css.bak`, `test_marker.txt`).

Команда подключается к `make check` через `python manage.py check &&
python manage.py check_staticfiles`.

Эффект: CI ловит расхождение до того, как кто-то увидит «Загрузка
чата...» в проде. Документируется в `Makefile`.

### C. Юнит-тесты на серверные контракты драйверов AI UI

В `apps/ai/tests.py` уже есть `test_native_ai_ui_config_*` (покрывают
`/ai/ui/config/`, `/ai/ui/session/new/`, `/ai/ui/session/clear/`,
`/ai/ui/ag-ui/run/`). Дополнить:

- `test_native_ai_ui_assets_present` — после `collectstatic` (или
  эквивалентной фикстуры) файл `staticfiles/src/ai_ui/native_ai.{js,css}`
  существует и не пуст;
- `test_native_ai_ui_dispatcher_excludes_legacy_when_native` —
  контекст-процессор возвращает `native_ai_ui_enabled=True` и
  `copilotkit_enabled=False`, если `LOCAL_BUSINESS_AI_UI_DRIVER=native`;
- `test_legacy_driver_disables_native_and_copilotkit` — симметрично.

В `apps/core/tests/test_check_staticfiles.py` — юнит-тесты команды
из пункта B:

- зеркальные файлы проходят проверку;
- отсутствующий staticfiles-копия выдаёт предупреждение с `--fail`
  превращает его в `CommandError`;
- legacy-артефакты в staticfiles (`.bak`, `test_marker.txt`)
  выдаются отдельно как «исторические следы».

## Альтернативы

### Сделать `collectstatic` обязательным шагом деплоя

Плюсы: минимальное кодовое изменение, фиксит инцидент 1 точечно.

Минусы: докомандный шаг легко забыть, никакого сигнала в CI, и
не помогает против инцидента 2 (забыли обновить asset version).

Отклонено: лечит симптом, не систему.

### Удалить CopilotKit, оставить только native и legacy

Плюсы: меньше драйверов, меньше boilerplate в шаблоне.

Минусы: ADR-0027/0028 явно закрепляют трёхдрайверную архитектуру
на переходный период, удаление требует отдельного ADR и обратной
совместимости.

Отклонено: за рамками задачи.

### Хранить asset-версию рядом с ассетом, как `//# version=...` комментарий

Плюсы: версия не теряется при переносе файла.

Минусы: всё равно ручное обновление; алгоритм «найти-и-распарсить»
хрупкий, если файл минифицируется.

Отклонено: авто-расчёт hash’а дешевле и надёжнее.

## Последствия

Положительные:

- рассогласование `static/src/` ↔ `staticfiles/` ловится в CI, а не в
  DevTools;
- забытый bump asset-версии становится невозможным по построению;
- юнит-тесты фиксируют трёхдрайверную матрицу поведения (legacy /
  native / copilotkit) как ожидаемый контракт для будущих рефакторингов;
- legacy-артефакты в `staticfiles/` становятся видимыми, их можно
  прибрать.

Отрицательные:

- `context_processors.py` делает `os.stat` на каждом запросе;
  кэширование на уровне процесса Django снимет это (см. ниже);
- `check_staticfiles` работает только если `manage.py` доступен в
  CI-агенте — для Windows-хоста это уже так;
- legacy-артефакты `native_ai.css.bak`, `test_marker.txt` остаются
  видны как предупреждения — намеренно, чтобы прибрать отдельно.

## Требования к реализации

- Изменения ограничены `apps/ai/context_processors.py`,
  `apps/core/management/commands/check_staticfiles.py`,
  `apps/ai/tests.py`, `apps/core/tests/test_check_staticfiles.py`,
  `Makefile`, `docs/adr/.desc.json`.
- Все временные артефакты писать в `.local/`.
- Кэширование hash’ов в `context_processors.py` — на уровне модуля
  (`functools.lru_cache` на чистую функцию, не на request).
- В `Makefile` команда `check` дополнительно зовёт
  `python manage.py check_staticfiles`.
- Добавить unit-тесты по новым веткам кода.
- Обновить проектную и исполнительную документацию в `docs/ai-ui/`.
