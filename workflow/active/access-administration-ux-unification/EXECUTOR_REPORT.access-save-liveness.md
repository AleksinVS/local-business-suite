# Executor report: access-save-liveness

## Результат

Зависание сохранения ролей и пользователей устранено на уровне блокировок и
HTMX-клиента. Длительные операции памяти/FileHub больше не используют
блокировку доступа.

## Изменения

- В `apps/core/file_locks.py` добавлен независимый
  `memory_source_lifecycle_lock_path()` с lock-файлом
  `.memory-source-lifecycle.lock`; lock ролей/пользователей сохранён отдельно.
- `enabled_source_operation`, status writer, ingestion projection, chat-memory
  indexing, reindex и безавторские FileHub baseline/incoming/sync/stats/move/
  purge используют memory-lock и существующие проверки включённости источника.
- Actor-aware FileHub operations сохранили fresh actor, policy, scope и
  fingerprint/snapshot guards. Операции, которым нужен source fence, получают
  блокировки только в порядке `access -> memory`; обратный порядок в изменённых
  участках отсутствует.
- Три формы access workspace получили `hx-request` с таймаутом 15 секунд,
  `hx-sync="this:drop"` и `hx-disabled-elt` для кнопок отправки. JS сохраняет
  dirty draft, дополнительно защищает от повторной отправки, снимает
  `aria-busy`/`htmx-request` после success, timeout,
  sendError, response/onLoadError, swapError и abort, и показывает русскую
  inline-ошибку. Cache-buster поднят до `access-workspace-v6`.
- Состояние HTMX-запроса хранится отдельно по `xhr`, форме и целевому узлу:
  завершение одного параллельного запроса больше не разблокирует другую форму.
- Таймаут вложенного FileHub memory-lock преобразуется сервисом в управляемую
  `ValidationError`, а не в HTTP 500.
- Добавлены регрессии независимости lock-path’ов, source lifecycle fence и
  выбора lock-контуров FileHub; E2E-пакет дополнен проверками idle-состояния
  после user/role apply/revert и сценариями aborted/hung POST.
- E2E-runner создаёт отдельный `LOCAL_BUSINESS_DATA_DIR` и выполняет
  `bootstrap_runtime`, поэтому применение и откат определения роли не меняют
  рабочие контракты разработчика.
- Обновлён `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

## Проверки

- `make verify-fast TEST_SCOPE=apps/core/tests.py` — **87 passed, 4 deselected, 12 subtests passed**.
- `make verify-fast TEST_SCOPE=apps/memory/tests/test_sources_and_models.py` — **9 passed, 5 subtests passed**.
- `make verify-fast TEST_SCOPE=apps/filehub/tests.py` — **43 passed, 24 subtests passed**.
- `make verify-fast TEST_SCOPE=apps/settings_center/tests.py` — **96 passed, 1 deselected, 35 subtests passed**.
- `make verify-profile PROFILE=memory` — **155 passed, 61 subtests passed**; архитектурные контракты валидны.
- `E2E_PORT=8020 E2E_ARTIFACT_DIR=.local/e2e-access-save-liveness bash scripts/e2e/run-smoke.sh` — **18 passed** в Chromium до цикла критики, включая фактическое применение/откат пользователя и определения роли.
- Финальный Chromium-набор после критики: **18 из 19 прошли одним прогоном**;
  новый тест параллельных форм потребовал исправления тестового запуска. После
  исправления отдельно прошли сценарий параллельных запросов (**1 passed**) и
  повторная проверка 15-секундного таймаута (**1 passed**). Остальные 18 в том
  же финальном прогоне прошли; продуктовый код между ними не менялся.
- `git diff --check` — успешно.
- `make verify-full` — **856 passed, 140 subtests passed**; system checks,
  staticfiles, migrations и architecture contracts прошли.

Первое содержательное падение: существующий FileHub-тест ожидал один вызов
`exclusive_file_lock` для actor-aware source operation. После корректного
добавления второго source-fence вызов стал `access -> memory`; тест обновлён и
весь узкий набор после этого прошёл.

## Риски и ограничения

- Глобальный memory-lock по-прежнему сериализует разные источники; per-source
  locks не вводились.
- Независимая критика выявила, что синхронные `accept/reject` знания и удаление
  устаревшего индекса всё ещё объединяют access authorization с Git/index I/O.
  Простая замена lock создала бы revoke-race, поэтому этот путь не изменён и
  вынесен в отдельный durable-фазовый пакет. Его ожидание уже ограничено
  серверными 10 секундами и клиентскими 15 секундами, то есть бесконечное
  состояние загрузки устранено, но редкая операция может завершиться просьбой
  повторить сохранение.
- Рабочие `data/contracts/` тестами не изменялись; браузерный прогон использовал
  `.local/e2e-access-save-liveness/data/contracts/`.

Архитектурное решение зафиксировано в принятом ADR-0041.
