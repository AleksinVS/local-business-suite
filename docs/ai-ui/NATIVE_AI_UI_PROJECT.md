# Native AI UI — проектная документация

## Что это

Native AI UI — это один из трёх UI-драйверов бокового ИИ-чата портала.
Драйвер отвечает за:

- разметку и поведение панели чата (sidebar, правый drawer,
  кнопки «Новый чат», «Очистить», смена модели);
- сериализацию сообщений и состояний (history, current model, in-flight
  run) для отрисовки;
- сетевой транспорт к серверу: `GET /ai/ui/config/` (инициализация),
  `POST /ai/ui/session/new/`, `POST /ai/ui/session/clear/`,
  `POST /ai/ui/ag-ui/run/` (стрим AG-UI событий);
- безопасное исполнение `ui.open_right_panel` через общий
  `LocalBusinessRightPanel` — без прямого доступа из фронтенда к
  доменной логике.

Native UI построен как явный peer-клиент AG-UI: он использует тот же
серверный контур `apps/ai/ui_runtime`, `services/agent_runtime/protocols`,
права, audit, историю и команды `ui.*`, что и альтернативный
драйвер CopilotKit. ADR-0027 и ADR-0028 фиксируют, что Native остаётся
основным целевым клиентом; CopilotKit подключён как эталон и
источник проверенных UX/runtime-паттернов.

## Цели

- Дать пользователю работающий боковой чат, эквивалентный по
  функциональности CopilotKit-варианту (те же эндпоинты, та же AG-UI
  семантика).
- Не зависеть от Node-сборки на проде: `static/src/ai_ui/native_ai.js`
  — единый непрерывный IIFE, который работает из Django staticfiles
  сразу после `manage.py collectstatic`.
- Пережить любые правки фронтенда без необходимости вручную
  подкручивать cache-bust query string.
- Пережить добавление новых файлов под `static/src/` без тихих регрессов
  в UI («Загрузка чата...» вместо панели).

## Границы

### В scope

- Шаблон sidebar-панели в `templates/base.html` и её CSS-токены
  (`app.css`, `src/ai_ui/native_ai.css`).
- Клиентский JS `static/src/ai_ui/native_ai.js` (AG-UI клиент,
  обёртка над `fetch`/`ReadableStream`).
- Контекст-процессор `apps/ai/context_processors.py` — вычисление
  asset-версий, dispatch трёх веток (legacy/native/copilotkit).
- Серверные эндпоинты `apps/ai/views.py:AIUIConfigView`,
  `AIUISidebarSessionNewView`, `AIUISidebarSessionClearView`,
  `AIUIAGUIRunProxyView`.
- Управляющая команда `manage.py check_staticfiles` — сверка
  `static/src/` ↔ `staticfiles/`.

### Вне scope

- Изменения серверного контура AG-UI (`services/agent_runtime/`).
- Замена legacy и copilotkit-веток: они остаются как есть.
- Визуальные правки общего header/sidebar — только класс
  `.sidebar-ai-panel` и его дети.

## Сценарии пользователя

1. **Аутентифицированный пользователь с `LOCAL_BUSINESS_AI_UI_DRIVER=native`.**
   Открывает любую страницу портала. В сайдбаре видит заголовок «ИИ-чат»,
   бейдж модели («GLM-4.5 Air»), пустое состояние с подсказкой,
   форму ввода. Отправляет сообщение — UI показывает «ИИ обрабатывает
   запрос…», затем стримит ответ. «Открыть полный чат» ведёт на
   `ai:chat_detail`. Кнопка «Новый чат» дёргает `session/new/`,
   «Очистить» — `session/clear/`.
2. **Неаутентифицированный пользователь.**
   Сайдбар показывает «Войдите, чтобы открыть ИИ-чат».
   На ветке `native` template не подключает `native_ai.js` (один из
   шаблонных `if/elif/elif/else`), поэтому попыток грузить клиент
   нет.
3. **Администратор с `LOCAL_BUSINESS_AI_UI_DRIVER=copilotkit`.**
   Видит тот же сайдбар, но шаблон подключает
   `dist/copilotkit/copilotkit-island.js` (модуль). Контекст-процессор
   устанавливает `copilotkit_enabled=True`, `native_ai_ui_enabled=False`.
4. **Разработчик правит `static/src/ai_ui/native_ai.js`.**
   Запускает `make check` — `manage.py check_staticfiles --fail`
   падает, если `collectstatic` не был запущен. После
   `manage.py collectstatic` тест зелёный. Asset-версия в `<script>`
   и `<link>` меняется автоматически (sha256 от mtime+size), без ручного
   bump'а `?v=...`.
5. **CI запускает `make check`.** Получает ненулевой exit-code, если
   `static/src/` и `staticfiles/` разошлись, и зелёный — иначе.

## Не-цели

- Не переписываем чат с нуля и не пытаемся догнать CopilotKit по UX —
  только поддерживаем стабильность существующего драйвера.
- Не выносим AG-UI в общий пакет с CopilotKit: общий у них только
  серверный контур (`apps/ai/ui_runtime/*`), но визуально они
  независимы.
- Не добавляем третий «runtime»-флаг: в проекте два runtime (Agent
  Runtime и CopilotKit Runtime) и три UI-драйвера — больше не нужно.

## Архитектурные решения

Связанные ADR:

- ADR-0019 «Контекстный ИИ-чат в левой боковой панели» — общая
  идеология чата.
- ADR-0027 «CopilotKit и AG-UI как дополнительный интерфейс ИИ-чата»
  — равноправный статус Native и CopilotKit.
- ADR-0028 «Версионируемая основа AI UI протоколов» — структура
  `apps/ai/ui_runtime/*`.
- **ADR-0029 «Авто-версии ассетов AI UI и проверка синхронности
  статики»** — основное решение этой работы: auto-sha256 asset
  versions, `manage.py check_staticfiles`, явная синхронизация
  `static/src/` ↔ `staticfiles/`.

## Связанные компоненты

| Слой | Файл | Роль |
| --- | --- | --- |
| Шаблон | `templates/base.html` (блок `sidebar_panel`) | Выбор ветки рендера sidebar-панели. |
| Контекст | `apps/ai/context_processors.py` | Вычисление `ai_ui_driver`, asset-версий. |
| Сервер | `apps/ai/views.py:AIUIConfigView` | `/ai/ui/config/` для клиента. |
| Сервер | `apps/ai/views.py:AIUISidebarSessionNewView` | `/ai/ui/session/new/`. |
| Сервер | `apps/ai/views.py:AIUISidebarSessionClearView` | `/ai/ui/session/clear/`. |
| Сервер | `apps/ai/views.py:AIUIAGUIRunProxyView` | `/ai/ui/ag-ui/run/` (SSE через AG-UI). |
| Клиент | `static/src/ai_ui/native_ai.js` | IIFE-клиент: история, форма, стрим. |
| Стили | `static/src/ai_ui/native_ai.css` | UI токены панели. |
| Инструменты | `apps/core/management/commands/check_staticfiles.py` | Сверка `static/src/` ↔ `staticfiles/`. |
| Конфиг | `.env` (host-specific, gitignored) | `LOCAL_BUSINESS_AI_UI_DRIVER`. |

## Требования

### Функциональные

- Sidebar-панель показывает история чата, текущую модель, форму ввода
  и управляющие кнопки.
- Кнопка «Открыть полный чат» переводит пользователя на полноэкранный
  чат `ai:chat_detail` с тем же `external_id`.
- Streaming ответа через AG-UI events: `RUN_STARTED`,
  `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_*`, `STATE_DELTA` (для
  `ui.open_right_panel`), `RUN_FINISHED`/`RUN_ERROR`.
- Очистка и создание новой сессии через REST.

### Нефункциональные

- **Согласованность статики**: после любого изменения
  `static/src/ai_ui/native_ai.{js,css}` команда `make check`
  должна вернуть `0`, иначе CI красный.
- **Cache-bust**: query string `?v=...` для JS и CSS обновляется
  автоматически при изменении файла, не требует ручного bump'а.
- **Совместимость**: переключение между native / legacy / copilotkit
  делается только через `LOCAL_BUSINESS_AI_UI_DRIVER` в `.env` —
  никаких пересборок, никаких ручных правок в шаблоне.
- **Ошибки**: ошибки инициализации клиента (404 на статику, пустой
  config, исключение в конструкторе) пишутся в `<div class="native-ai-ui-error">…</div>`
  внутри панели, а не теряются молча.

### Безопасность и приватность

- Все запросы идут с `credentials: "same-origin"` и CSRF-токеном
  (`csrftoken` cookie). Серверные эндпоинты — за `LoginRequiredMixin`.
- Streaming-точка `/ai/ui/ag-ui/run/` принимает только
  `forwardedProps` с HMAC-подписью от Agent Runtime; client-side
  подделать payload нельзя.
- Команды `ui.*` ограничены whitelist'ом: `open_right_panel` — единственная
  разрешённая; всё прочее игнорируется (`executeUiCommand`).
- В `native_ai.js` весь пользовательский ввод показывается через
  `escapeHtml()`; шаблоны собираются в массивы строк, без `eval`/
  `Function`.

## Риски и допущения

- **Расхождение `static/src/` ↔ `staticfiles/`** — теперь ловится
  `check_staticfiles --fail` (ADR-0029). Остаточный риск: если
  разработчик правит файл и коммитит, но забывает `collectstatic`,
  тест пропустит до момента запуска CI; в проде ассеты подаются из
  снэпшота `staticfiles/`, поэтому на хосте всё будет работать.
  Допущение: CI запускается на каждый push.
- **HMR (hot reload) в dev.** `runserver` читает `static/src/` напрямую
  через `django.contrib.staticfiles`, поэтому в DEBUG-режиме
  изменения JS видны без `collectstatic`. Asset-версия в HTML, однако,
  пересчитывается на каждом запросе (mtime), так что cache-bust
  корректен.
- **Большие статики.** Если файл вырастет до сотен килобайт,
  хэш-вычисление на каждый запрос станет заметным. Решение —
  перенести кэш в `__init__.py`-уровень процесса через `cachetools` или
  обновлять версию из management command (вне scope).
- **Manifest-stripping при collectstatic.** `ManifestStaticFilesStorage`
  оставляет `app.<hash>.css`-копии. Они учтены в
  `_MANIFEST_HASH_RE` фильтре `check_staticfiles` как legacy.

## План валидации

1. `python manage.py check` — должен вернуть `0`.
2. `python manage.py check_staticfiles --fail` — должен пройти после
   `collectstatic`.
3. `python manage.py test apps.ai.tests_context_processors apps.core.tests.CheckStaticfilesCommandTests -v 2`
   — все 16 тестов зелёные.
4. `python manage.py validate_architecture_contracts` — должен остаться
   зелёным.
5. Включение `LOCAL_BUSINESS_AI_UI_DRIVER=native` в локальном `.env`,
   перезапуск пула приложения IIS / `runserver`. В DevTools браузера
   на любой странице:
   - запрос `/static/src/ai_ui/native_ai.js?v=<hash>` возвращает 200;
   - в DOM появляется `<div class="native-ai-ui">` (не остаётся
     «Загрузка чата...»);
   - отправка тестового сообщения рисует ответ стримом.
6. Переключение `.env` обратно на `legacy` — должно остаться
   работоспособным без правок кода.

## Открытые вопросы и отложенные идеи

- Подключить `manage.py check_staticfiles` в pre-push hook через
  `.git/hooks/pre-push` — улучшит улов расхождений ещё до CI.
- Заменить ручное обновление JS на полноценный bundler (esbuild) —
  отложено: требует ещё одного ADR и инфраструктурного шага.
- Добавить e2e проверку чата (Playwright/Selenium) под feature flag —
  в backlog'е отдельной задачей.
