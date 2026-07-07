# Executor report: 10-sqlite-legacy-cleanup

Дата: 2026-07-07
Исполнитель: Claude agent (executor)
Пакет: `workflow/active/architecture-review-remediation-2026-07-04/task-packets/10-sqlite-legacy-cleanup.json`
Контекст: ADR-0029 (dev-стадия, production-данных нет — миграция данных не требуется).

## Что сделано

### 1. `apps/core/db_routers.py` — удалён

No-op `LocalBusinessDatabaseRouter` не был подключён (`DATABASE_ROUTERS = []` в
`config/settings.py`). Проверено, что нигде в коде класс не импортируется и не
используется — мёртвый файл. Удалён полностью.

### 2. `config/settings.py` — убраны три артефакта

- `DATABASE_ROUTERS = []` заменена на комментарий на том же месте, поясняющий,
  что список пуст осознанно (единственная база `default`, ADR-0029), а не
  забыт как настройка без реализации. Выбран вариант «оставить с комментарием»,
  а не тихое удаление строки: без строки в файле не осталось бы явного следа,
  что маршрутизация рассматривалась и закрыта архитектурным решением — при
  следующем ревью кто-то может снова завести вопрос «а где роутер»; комментарий
  закрывает его на месте.
- `LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES` (словарь путей default/chat/
  knowledge_meta/analytics_control с env-override `LOCAL_BUSINESS_LEGACY_SQLITE_*_PATH`)
  — удалён из settings. Логика перенесена в `apps/core/postgresql_migration.py`
  (см. п.3) — конфиг инструмента миграции не должен жить в глобальных
  Django settings, которые читает всё приложение.
- `LOCAL_BUSINESS_DB_SPLIT_ENABLED = False` — удалена (проверено оркестратором
  и повторно grep-ом: нет ни одного вхождения где-либо ещё в коде).

### 3. `apps/core/postgresql_migration.py` — словарь путей перенесён сюда

`legacy_sqlite_databases()` больше не читает `settings.LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES`,
а строит тот же словарь путей напрямую из `os.environ` (семантика env-override
`LOCAL_BUSINESS_LEGACY_SQLITE_*_PATH` и дефолты `DATA_DIR / "db" / "*.sqlite3"`
сохранены 1:1, `DATA_DIR` берётся через `settings.DATA_DIR`, который остаётся
глобальной настройкой и не удалялся). Добавлен docstring, объясняющий, почему
конфиг здесь, а не в settings, и для чего он вообще ещё нужен (export/import/
validate + миграция legacy chat/analytics баз, до production cutover).

### 4. Два потребителя переведены на новый источник

- `apps/ai/management/commands/migrate_legacy_chat_db.py`
- `apps/analytics/management/commands/migrate_legacy_analytics_control_db.py`

Оба вместо `getattr(settings, "LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES", {})`
теперь импортируют и вызывают `apps.core.postgresql_migration.legacy_sqlite_databases()`.
Поведение команд не менялось — проверено вручную `--dry-run` на обеих командах
после правки (см. «Ручная проверка» ниже), пути и найденные таблицы/счётчики
совпадают с ожидаемыми.

Правка этих двух файлов выполнена по явному расширению write_scope от
оркестратора (в исходном JSON-пакете эти файлы не были учтены как потребители).
Дальше по цепочке (построение путей, тесты) ничего не поехало — расширения
правок за пределы согласованного списка не потребовалось.

### 5. `apps/core/tests.py` — три теста переведены на новый механизм

`test_postgres_migration_export_reads_legacy_sqlite_manifest`,
`test_postgres_migration_export_prefers_domain_sqlite_source`,
`test_postgres_migration_package_validation_checks_jsonl_counts` — раньше
использовали `override_settings(LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES=...)`
(настройка, которой больше не существует). Заменено на
`unittest.mock.patch("apps.core.postgresql_migration.legacy_sqlite_databases", return_value=...)` —
паттерн для локального импорта `patch` внутри теста уже использовался в этом
файле (`test_fail_on_drift_flag_exits_nonzero_only_when_drift_present`), выдержан
тот же стиль. `override_settings` остаётся импортированным и используется в
24 других местах файла — импорт не тронут.

### 6. `apps/core/.desc.json` — убрана запись `db_routers.py`

Описание `postgresql_migration.py` дополнено фразой про перенос словаря путей
(конфиг инструмента миграции, не глобальная настройка). `PROJECT_STRUCTURE.yaml`
не трогал — по инструкции регенерирует оркестратор (`make gen-struct` не запускал).

### 7. `docs/deployment/POSTGRESQL_MIGRATION.md`

Проверен на ссылки на удалённые настройки/роутер — не найдено ни одного
вхождения (`LOCAL_BUSINESS_LEGACY_SQLITE`, `db_routers`, `DATABASE_ROUTERS`,
`DB_SPLIT`). Правки не потребовались.

## Файлы, изменённые пакетом (git status)

```
M apps/ai/management/commands/migrate_legacy_chat_db.py
M apps/analytics/management/commands/migrate_legacy_analytics_control_db.py
M apps/core/.desc.json
D apps/core/db_routers.py
M apps/core/postgresql_migration.py
M apps/core/tests.py
M config/settings.py
```

Все — в пределах согласованного (расширенного оркестратором) write_scope.
Другие файлы не трогал; не коммитил (по инструкции).

## Grep-проверки (обязательные)

```
grep -rn "DB_SPLIT_ENABLED\|db_routers\|LocalBusinessDatabaseRouter" apps/ config/ services/ --include=*.py
```
→ 0 вхождений.

```
grep -rn "settings.LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES\|LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES" apps/ config/ --include=*.py
```
→ 0 вхождений вообще (во всём репозитории, не только в `apps/`/`config/`) —
константа `LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES` удалена полностью. Новый
источник называется иначе — функция `legacy_sqlite_databases()` (нижний регистр)
в `apps/core/postgresql_migration.py`; потребители (`migrate_legacy_chat_db.py`,
`migrate_legacy_analytics_control_db.py`, тесты) вызывают/патчат именно её.

## Проверки (acceptance)

1. **`.venv/bin/python manage.py test`** (полный набор, regression):

   ```
   Ran 432 tests in 709.131s
   OK
   ```

2. **`.venv/bin/python manage.py check`**:

   ```
   System check identified no issues (0 silenced).
   ```

3. **`.venv/bin/python manage.py migrate --check`**:

   На текущей dev sqlite (`data/db/local_business.sqlite3`) выходит с кодом 1 —
   **но это не связано с этим пакетом**: причина — пять неприменённых миграций
   (`core.0006_department_oid`, `inventory.0006_medicaldevice_building_and_more`,
   `inventory.0007_catchall_department`, `inventory.0008_alter_medicaldevice_serial_and_more`,
   `inventory.0009_alter_medicaldevice_options_and_more`), которые уже были
   закоммичены раньше (коммит `e1951a8`, до начала этой задачи) и просто ни разу
   не применялись к локальной dev-базе на этой машине. `git status` подтверждает,
   что кроме файлов из write_scope этого пакета ничего не менялось — миграции
   и модели я не трогал.

   Проверил альтернативный путь из acceptance_checks («или прогон миграций на
   чистой sqlite dev-базе»): на чистой временной sqlite-базе (`LOCAL_BUSINESS_SQLITE_PATH`
   указывал на новый пустой файл) `manage.py migrate` отработал полностью и
   успешно (все миграции всех приложений применились, exit 0), последующий
   `manage.py migrate --check` на этой же чистой базе — exit 0. Это и есть
   критерий пакета, он выполнен.

   Остаточный факт вне scope этой задачи: локальную dev-базу стоит догнать
   (`manage.py migrate`) отдельным действием — не делал этого сам, так как
   это не относится к SQLite-legacy-cleanup и не входит в write_scope пакета.

## Ручная проверка команд после переноса источника путей

```
.venv/bin/python manage.py migrate_legacy_chat_db --dry-run
.venv/bin/python manage.py migrate_legacy_analytics_control_db --dry-run
```

Обе команды отработали, показали ожидаемые legacy/target счётчики по таблицам
(`ai_chatsession`, `ai_chatmessage`, ..., `analytics_*`) — пути резолвятся
корректно через новый `legacy_sqlite_databases()` в `postgresql_migration.py`.

## Отклонения от постановки

Отклонений от согласованного (расширенного оркестратором) плана нет. Перенос
словаря путей не породил расползания правок за пределы согласованного списка
файлов — стоп-условие из инструкции («если рябь пойдёт дальше — остановиться»)
не сработало.

## Методологическая заметка (для владельца, backend learning)

**Почему конфиг миграционного инструмента не должен жить в глобальных Django
settings.** `settings.py` — это конфигурация *приложения как целого*: она
импортируется при старте любого процесса (веб-воркер, Celery/RQ worker,
management-команда, тестовый раннер) и должна содержать только то, что нужно
для нормальной работы приложения в этом запуске. `LOCAL_BUSINESS_LEGACY_SQLITE_DATABASES`
нужен ровно трём management-командам, которые выполняются вручную оператором
один раз на этапе миграции на PostgreSQL — остальным 99% кода эти пути вообще
не нужны, но они всё равно вычислялись при каждом импорте settings (лишний
`os.environ.get` + `Path(...)` на старте каждого процесса) и были видны как
часть "публичного API" настроек проекта, хотя реально были приватной
деталью реализации трёх файлов. Перенос словаря в модуль, который его
единственно использует (`apps/core/postgresql_migration.py`), — это обычный
принцип «конфигурация должна жить рядом с кодом, который её потребляет»
(low coupling): теперь видно из одного файла и что нужно, и зачем, и кто
это использует; settings.py не разрастается артефактами, которые переживут
свою полезность и никто не решится удалить, потому что непонятно, кто на них
опирается.

**Почему no-op роутер и мёртвая константа — это шум, вводящий в заблуждение.**
`LocalBusinessDatabaseRouter` ничего не делал (`db_for_read`/`db_for_write`
всегда возвращали `None` — «используй дефолтный alias»), но само его
присутствие в кодовой базе плюс докстринг «Legacy router for the archived
SQLite split» заставляет любого, кто впервые читает код, тратить время на
выяснение: а не влияет ли он на что-то, не надо ли его учитывать при
изменении моделей. Та же история с `LOCAL_BUSINESS_DB_SPLIT_ENABLED = False` —
константа, которую никто не читает: она выглядит как переключатель feature
flag, провоцируя вопрос «а что будет, если включить», хотя ответ — «ничего,
никто её не проверяет». Мёртвый код и мёртвая конфигурация опаснее отсутствия
кода: они создают ложную видимость активной архитектуры и увеличивают
когнитивную нагрузку при каждом последующем ревью или онбординге нового
разработчика, не давая взамен никакой функциональности.
