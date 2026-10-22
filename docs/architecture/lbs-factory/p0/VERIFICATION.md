# Проверки исходного состояния P0

Дата: 2026-10-22. HEAD: `2c250ae30e496434e479043ad9db84c758bce0ba`.
Python 3.12.3, Linux, SQLite. Production не подключался.

## Оглавление

- [Граница выполнения](#граница-выполнения)
- [Первое падение и профиль проверки](#первое-падение-и-профиль-проверки)
- [Исходная матрица](#исходная-матрица)
- [Новый HTTP-сценарий](#новый-http-сценарий)
- [Измерения](#измерения)
- [Восстановление снимка](#восстановление-снимка)
- [Утилита хоста](#утилита-хоста)
- [Воспроизведение](#воспроизведение)
- [Оставшиеся условия](#оставшиеся-условия)

## Граница выполнения

Перед началом и проверками сохранён `git status --short`. Изначально — только
существующий незарегистрированный файл в `drafts/`, который не читался/не менялся.
Прикладной код, `contracts/`, `.env`, настройки хостов и рабочие данные не менялись.

Независимые исследователи читали Access/модульность, Privacy/Wiki и runtime;
основной агент проверял существенные находки и выполнял команды. Упоминание
«тесты не запускались» в их статических отчётах относится к роли исследователя.

## Первое падение и профиль проверки

Обычный `make verify-fast` остановился **до pytest** на system check:
`core.E001` и `settings_center.W001`. Local process использует SQLite,
но allowlist включает 14 PostgreSQL-backed документов.

После падения выполнен `make test-failed TEST_SCOPE=...` с Git-default путями
четырёх контрактов и пустым DB allowlist **только для процесса**:
266 passed, 20 subtests passed; pytest 63,41 с, команда 72,53 с.
Затем `make verify-fast` подтвердил system check и ту же выборку:
266 passed, 20 subtests passed; pytest 48,17 с, команда 64,29 с.
Это два запуска тех же сценариев, **не 532 разных теста**.

Сохранилось `settings_center.W002`: состояние миграции runtime documents
локально недоступно. `.env` не исправлялась, PostgreSQL backend этим не проверен.
`make contracts` — код 0, `Architecture contracts are valid`; drift сообщает
4 explicit overrides и 10 недоступных legacy зеркал. Это не проверка рабочих
документов Windows-хоста.

## Исходная матрица

Фактически запущены:

```text
apps/accounts/tests.py::AccessAssignmentServiceTests
apps/workorders/tests.py::WorkOrderRoleMatrixTests
apps/workorders/tests.py::WorkOrderViewPermissionTests
apps/warehouse/tests/test_access.py
apps/waiting_list/tests.py
apps/memory/tests/test_policy_and_privacy.py
apps/memory/tests/test_review_boundaries.py
apps/ai/tests/test_native_execution.py
services/agent_runtime/tests/test_contract_delivery.py
```

| Граница | Исходное поведение |
|---|---|
| Accounts | protected roles, self-escalation, last-superuser, stale target, технические группы, audit |
| WorkOrders | roleless/outsider deny, scopes, board ACL, workflow, HTTP |
| Warehouse | inactive/roleless deny, whole-role, подразделение/ветка, отзыв |
| Waiting List | роли/статусы, scope+targets одной роли, свежесть на записи, HTTP/HTMX, audit/import |
| Memory | source/item scope, direct-read active actor, adapter access, local deidentification |
| AI | чужие сессии, forged thread, replay/fence, delivered policy/catalog |

Другие node IDs в статических отчётах — **найденное покрытие**, а не результат
запуска. Весь ingestion/indexing/chat/reconcile, PostgreSQL concurrency и
отдельные AG-UI signature tests целиком не запускались. PRIV-разрывы открыты.

## Новый HTTP-сценарий

[Исходник локальной проверки](../../../../workflow/active/lbs-factory-p0/BASELINE_CHECKS.md)
запущен явно через `make verify-fast TEST_SCOPE=workflow/active/lbs-factory-p0/baseline_checks.py`
(исторический путь, затем перенесён без изменения кода в `.local`):
**1 passed**, pytest 14,84 с, команда 29,29 с.

Проверена связка Django client → HTTP → policy/service → ORM → audit:

1. Полностью вычисленные выборки 100/1000 синтетических строк.
2. Постороннему dashboard/detail возвращают 403 без текста записи.
3. По Git-default doctor читает чужую запись (200), но update/transition
   получают 403; чужие поля и audit не изменяются.
4. Создание → чтение → изменение комментария → смена статуса своей записи;
   ровно три правильных события аудита.

Тест требует `config.settings_test`, SQLite и test DB внутри `.local`.
Все временные пути — `.local`, TestCase откатывает синтетические строки.
Это HTTP application e2e, не браузерный/IIS/AD сценарий.

## Измерения

Тёплые последовательные выборки, nearest-rank percentiles; включены накладные
расходы SQL capture и Django client. SLA и production capacity не измерялись.

| Операция | Замеров | p50, мс | p95, мс | SQL |
|---|---:|---:|---:|---:|
| Selector ID, 100 строк | 20 | 2,10 | 6,32 | 2 |
| Selector ID, 1000 строк | 20 | 2,14 | 5,69 | 2 |
| Полный HTML, 1000 строк | 10 | 1030,36 | 1319,51 | 24 |
| Собственная detail | 10 | 81,60 | 108,31 | 29 |

Один SQL selector читает группы, второй записи; число не растёт при 100→1000.
Это доказательство только данного пути, не всей матрицы прав на 1000 объектов.
Dashboard `apps/waiting_list/views.py:131` отрисовывает все строки без пагинации;
это исходное наблюдение, не исправление P0 и не причина смены стека.
Числовые замеры и contract SHA256 — `.local/lbs-factory-p0/metrics.json`;
SQL и пользовательские значения туда не пишутся. Разовые write/deny вызовы
проверяют поведение, их percentiles статистически не интерпретируются.

## Восстановление снимка

В `.local/lbs-factory-p0/snapshot/` сохранены код HEAD, SQLite backup API-снимок
и файловый `data/` с `.git` Wiki. SHA256 — `local-snapshot.json`; каталог закрыт
для других пользователей. `.env`/ключи не копировались: это не полный deployment
backup и не копия Windows-хоста.

Отдельный `restore-check/`: integrity=ok, 0 FK violations, counts совпали
по 80 таблицам, SHA256 копии БД совпал, knowledge Git `fsck --full` — код 0.
Рабочие данные не заменялись. Приложение/reindex/reconcile на восстановленной
копии не запускались: это проверка восстановления снимка, **не полного сервиса**.
Файловый архив не объявляется атомарной копией активно изменяемого сервера.

## Утилита хоста

[host_inventory.py](../../../../workflow/active/lbs-factory-p0/host_inventory.py)
запущен на отдельном SQLite-снимке с Git-default settings: код 0, обязательные
таблицы присутствуют, ошибок нет. SHA256 БД до/после совпал. После независимого ревью также проверены
отсутствующий Git в PATH (отчёт сохранён, SHA отмечен как неизвестный) и заранее
существующая ссылка с фиксированным именем tmp (не была открыта, целевой файл
не изменился). Уникальный промежуточный файл создаётся exclusive. Вывод в корень
проекта отклонён кодом 2; файл вне `.local` не создан.

PostgreSQL защищён read-only транзакцией, SQLite — URI mode=ro/query_only.
**PostgreSQL и Windows исполнения не было**. Утилита не экспортирует строки,
индивидуальные права, секреты или role document. `django.setup()` исполняет
код установленной версии; неизвестные старые расширения проверяет оператор.
Она собирает настройки своего процесса, не подтверждает IIS worker environment
и не выполняет backup. [Инструкция](MIGRATION_AND_RECOVERY.md#проверка-на-windows-сервере).

## Воспроизведение

Сначала извлечь исходник по инструкции в BASELINE_CHECKS.md (выше).
Из корня проекта в Bash, с процессными overrides:

```bash
mkdir -p .local/lbs-factory-p0/tmp
env LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST='' \
  LOCAL_BUSINESS_ROLE_RULES_FILE="$PWD/contracts/role_rules.json" \
  LOCAL_BUSINESS_WORKFLOW_RULES_FILE="$PWD/contracts/workflow_rules.json" \
  LOCAL_BUSINESS_WORKORDER_STATUS_COLORS_FILE="$PWD/contracts/workorder_status_colors.json" \
  LOCAL_BUSINESS_WAITING_LIST_STATUS_COLORS_FILE="$PWD/contracts/waiting_list_status_colors.json" \
  TMPDIR="$PWD/.local/lbs-factory-p0/tmp" \
  PYTHONPYCACHEPREFIX="$PWD/.local/pycache" \
  make verify-fast TEST_SCOPE=.local/lbs-factory-p0/test_p0_baseline.py
```

Для исходной матрицы заменить TEST_SCOPE списком выше, для `make contracts`
использовать те же overrides. Это **локальный** профиль; на Windows для сбора
реальных сведений overrides не подставлять.

Генерация выполнена штатным `make gen-struct` в изолированном зеркале
исходников `.local/lbs-factory-p0/structure-source/`; результат скопирован
в корень без ручной правки. Причина: существующий генератор не исключает `.local`
и иначе публикует структуру временных checkout. В зеркале нет локального
состояния/секретов; генератор и его формат не менялись. Его ограничение глубины
также показывает вложенные каталоги как `file`; подробная навигация P0
сохраняется в 13_P0_BASELINE.md. Это отдельный долг инструмента карты.

После последних правок: генерация, проверка ссылок/описаний,
`git diff --check`; итог — в [приёмке](../../../../workflow/active/lbs-factory-p0/TASK_ACCEPTANCE.01-inventory.md).

## Оставшиеся условия

Нужны отчёт Windows/IIS, фактические роли/назначения/permission mapping,
закрытые hashes переносимых данных, реальная backup/restore и вход AD/IIS.
Count-only отчёт не заменяет эти проверки. По версии исходной схемы выбрать
способ переноса; обычный WL importer и общий helper пока недостаточны.
Не включать новые Wiki/AI пути на реальных ПДн до PRIV/Access и политики назначения.

Полный `make verify-full` и общие профили не запускались: приложения/контракты
не менялись; выполнены исходная выборка и проверки вспомогательных артефактов.
Для следующего крупного блока реализации полный набор обязателен по AGENTS.md.
