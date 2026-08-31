# Упрощение хранения и доставки настроек

Статус: ADR-0048 принят; пакеты 01–03 и dev/test-часть пилота 04 реализованы и
приняты. Production-пилот ожидает отдельного операционного разрешения, миграции
схемы, backup и окна наблюдения.

Дата: 2026-08-31.

Связанные материалы:

- ADR: `docs/adr/ADR-0048-typed-setting-documents-and-postgresql-runtime-state.md`;
- проектная архитектура:
  `docs/architecture/SETTINGS_STORAGE_TARGET_ARCHITECTURE.md`;
- workflow-блок: `workflow/active/settings-storage-simplification/`;
- действующие решения: ADR-0007, ADR-0029, ADR-0031;
- операции текущего Центра настроек:
  `docs/guides/SETTINGS_CENTER_OPERATIONS.md`.

## Цель и ценность

Перевести изменяемые рабочие настройки с зеркальных JSON-файлов на
типизированные документы PostgreSQL, сохранив Git-дефолты, доменные валидаторы,
права и аудит.

Пользовательская ценность:

- изменение применяется всем процессам без перезапуска;
- нет расхождения между тем, что показывает Центр настроек, и тем, что использует
  AI/memory/agent-runtime;
- rollback и история остаются понятными;
- связанные настройки можно показывать на одном экране без создания одного
  гигантского файла;
- ошибки конфигурации дают видимый и предсказуемый результат.

Инженерная ценность:

- один registry и repository вместо повторяющихся списков;
- одна транзакция для значения и audit;
- удаление staged file/DB reconciliation для мигрированных документов;
- отсутствие default/runtime file drift;
- явные schema migrations вместо ручного слияния JSON.

## Фактическая исходная точка

- 29 JSON-документов значений в Git и 29 runtime-копий;
- 33 `SettingDescriptor`;
- 18 runtime descriptors, 17 editable;
- четыре документа в `apps.core.contract_store`;
- AI/memory/FileHub/analytics в основном используют startup payload constants;
- agent-runtime имеет отдельный resolver AI-файлов;
- `SettingsChange` уже содержит before/after snapshots и пригоден как журнал
  версий;
- production main работает на PostgreSQL с 2026-08-18.

Snapshot `validate_architecture_contracts` от 2026-08-31: 10 контрактов
совпадают с дефолтом, 7 имеют runtime-отличия, а `core.contract.role_rules`
отстаёт по default-only ключам `$defaults` и `viewer`. Последний случай является
security migration gate: автоматический merge запрещён, требуется сверка с
ADR-0045 и фактической матрицей доступа.

## Scope

1. Машинно читаемый инвентарь и классификация всех конфигурационных документов.
2. Единый доменно-регистрируемый `ConfigDocumentSpec`.
3. `RuntimeSettingDocument`, repository и транзакционный writer.
4. Версии схем, content hash, revision/CAS и health state.
5. Идемпотентный migration planner/importer для legacy runtime JSON.
6. Pilot на независимом документе цветов листа ожидания; обе палитры остаются
   отдельными документами.
7. Перевод role/workflow с независимой security-приёмкой.
8. Django gateway и доставка AI-документов в agent-runtime по ETag.
9. Перевод memory/FileHub consumers со startup constants на repository.
10. Классификация analytics/integrations и удаление лишних runtime-копий.
11. Обновление операций, backup/restore, health и архитектурной документации.

## Non-goals

- менять бизнес-смысл контрактов;
- объединять документы по одному только признаку общей страницы UI;
- внедрять универсальный form generator или `x-ui` в первом срезе;
- добавлять Redis, Celery, pub/sub или новый service;
- хранить секреты в payload/audit;
- поддерживать постоянную двойную запись file+DB;
- удалять legacy-файлы до backup, наблюдения и acceptance;
- переводить runtime AI skills или файлы знаний в `jsonb`;
- вводить YAML как каноническое рабочее хранилище.

## Решения, обязательные до реализации

- владелец принимает или изменяет ADR-0048;
- утверждается предварительная классификация 29 документов;
- подтверждается короткое окно заморозки записи для каждого cutover slice;
- утверждается fail-closed поведение role/workflow и last-known-good поведение
  agent-runtime;
- backup/recovery review учитывает новые DB-документы;
- определяется, остаётся ли `ai.contract.models` Git-static или становится
  управляемым документом.

## Предполагаемый write scope реализации

- `apps/core/` — transport registry/repository, checks, migration tooling;
- `apps/settings_center/` — модель, миграции, writer, audit, UI adapter;
- доменные `settings_descriptors.py`/новые `config_documents.py`;
- потребители в `apps/accounts`, `apps/workorders`, `apps/waiting_list`,
  `apps/ai`, `apps/memory`, `apps/filehub`, `apps/analytics`;
- `services/agent_runtime/` и существующий Django AI gateway;
- `config/settings.py` и `bootstrap_runtime` только для удаления legacy payload
  loading после миграции;
- тесты затронутых приложений и постоянные e2e management commands/specs;
- `docs/adr`, `docs/architecture`, `docs/deployment`, `docs/guides`, planning и
  workflow;
- `.desc.json`, `PROJECT_STRUCTURE.yaml`.

Изменение `contracts/` допускается только для schema version/migrator metadata и
валидных обновлённых дефолтов. Рабочие данные в `data/` не коммитятся.

## Порядок работ

### Пакет 01. Инвентарь и единый registry

- сформировать полный классифицированный inventory;
- ввести `ConfigDocumentSpec` и fail-fast проверки registry;
- построить runtime descriptors для документов из спецификаций;
- не менять backend чтения/записи;
- доказать отсутствие второго списка validator/path для новых документов.

Результат: единый каталог готов, поведение прежнее.

### Пакет 02. PostgreSQL document store

- добавить модель/миграцию `RuntimeSettingDocument`;
- реализовать repository, request snapshot, hash/schema checks;
- реализовать транзакционный writer и DB rollback;
- расширить `SettingsChange` ревизиями документов;
- сохранить legacy writer отдельно до cutover.

Результат: новый backend проверен на синтетическом документе, production
документы ещё не переключены.

### Пакет 03. Migration planner и операции

- реализовать `settings_documents_migrate --plan/--apply`;
- использовать Git hash, runtime hash и audit evidence;
- не импортировать неоднозначный drift автоматически;
- добавить export/diagnostics/health;
- подготовить backup и rollback runbook.

Результат: dry-run даёт исчерпывающий и идемпотентный план.

### Пакет 04. Pilot цвета статусов листа ожидания

- перевести независимый `waiting_list.contract.status_colors` на DB backend;
- оставить палитру заявок на legacy backend до согласованного перехода с
  workflow;
- показать их рядом в существующем UX;
- выполнить multi-worker и UI e2e;
- выдержать окно наблюдения перед следующим срезом.

Результат: первый безопасный proof of architecture.

### Пакет 05. Access/workflow/status-colors security slice

- перевести role/workflow и палитру заявок одной согласованной волной;
- сохранить специальные команды изменения ролей;
- заменить прямые file/settings reads;
- проверить roleless access, default role, privilege ceiling, role copy и
  workflow transition matrix;
- выполнить независимую security-проверку.

Результат: авторизация использует один DB-снимок без изменения семантики.

### Пакет 06. AI и agent-runtime delivery

- добавить allowlisted read-only config endpoint в существующий Django gateway;
- ETag/conditional request и diagnostics;
- сделать AI registry/tools/task types Git-static и убрать их из generic runtime
  editor: они задают identity, tool/code parity и confirmation policy;
- перевести chat settings в DB, а models — только после отдельного решения;
- доставлять через gateway единый набор Git-static и DB-effective документов;
- добавить last-known-good cache и schema checks agent-runtime;
- удалить прямой file resolver только после parity/e2e.

Результат: Django и agent-runtime сообщают одинаковые hashes/revisions.

### Пакет 07. Memory/FileHub и статические документы

- перевести memory consumers и commands на repository snapshots;
- FileHub получает profile snapshot на начало операции;
- классифицировать analytics/integrations как Git-static, DB-managed или
  generated — только с явным владельцем;
- не менять memory knowledge canon и AG-UI wire contract.

Результат: startup payload constants больше не являются runtime API.

### Пакет 08. Cleanup, recovery и финальная приёмка

- прекратить bootstrap-копирование переведённых документов;
- удалить legacy registry/file locks/reconcile код после доказанного отсутствия
  потребителей;
- обновить health, deployment, operations, backup/restore и README;
- выполнить полный e2e и один `make verify-full`;
- архивировать workflow только после пользовательской и технической приёмки.

## Зависимости и порядок

Обязательный порядок:

```text
01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07 -> 08
```

После пакета 04 допускается параллельная предварительная подготовка 05 и 06, но
их production cutover не выполняется одновременно. Пакет 08 начинается только
после завершения всех cutover slices.

## Стратегия миграции и rollback

- не использовать долгоживущий shadow write;
- каждый срез имеет freeze, final plan, backup, apply, switch, smoke и observation;
- runtime file, не отличающийся от Git default, не создаёт DB override;
- подтверждённый audit-снимок импортируется с сохранением hashes;
- неоднозначный drift блокирует автоматический cutover;
- rollback разрешён, пока после cutover не появилось несовместимых новых
  ревизий;
- после новых ревизий возврат требует управляемого export, а не переключения на
  старый файл;
- удаление legacy-файла выполняется только в пакете 08.

## Матрица проверок

### На каждом пакете

```bash
git status --short
make verify-fast TEST_SCOPE=<затронутые тесты>
git diff --check
```

### При межкомпонентном изменении

```bash
make verify-profile PROFILE=contracts
make verify-profile PROFILE=ui
```

AI-срез дополнительно:

```bash
make verify-profile PROFILE=ai
```

### Обязательные точечные проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test apps.core.tests apps.settings_center.tests
```

По срезам добавляются доменные тесты accounts/workorders/waiting_list, AI,
memory/FileHub и agent-runtime.

### Финальная приёмка

```bash
make verify-full
```

Постоянный e2e должен проверять основной пользовательский сценарий через UI/API,
а не только repository. Временные отчёты и логи пишутся в `.local/`.

## Критерии готовности (Definition of Ready)

- ADR-0048 принят;
- inventory подтверждён владельцами доменов;
- каждый packet имеет точный read/write scope и rollback;
- тестовый PostgreSQL профиль доступен;
- выбран независимый `waiting_list.contract.status_colors` для первого pilot;
- backup и freeze procedure согласованы;
- ни один документ с secret-bearing payload не попал в scope;
- для security/AI/memory срезов назначена независимая проверка.

## Критерии завершения (Definition of Done)

- все управляемые документы имеют одну спецификацию;
- переведённые документы читаются только через repository;
- нет startup payload constants для runtime-managed документов;
- DB value и audit фиксируются одной транзакцией;
- stale edit, rollback и schema migration проверены;
- multi-worker и agent-runtime parity проверены;
- legacy runtime copies и reconcile удалены либо явно перечислены как остаток;
- backup/restore подтверждает value + audit continuity;
- документация и карта проекта обновлены;
- завершённая задача удалена из backlog;
- workflow содержит executor reports, acceptance reports и retrospective, затем
  перенесён в архив.

## Риски

- ошибочная миграция role rules может изменить доступ — отдельный security slice,
  fail-closed и матрица ролей обязательны;
- незамеченный consumer startup constant продолжит видеть старое значение —
  запрещающие `rg`/architecture tests обязательны;
- agent-runtime может остаться на last-known-good — age/source/hash должны быть
  видимы в health;
- default/schema update может потребовать ручного migrator — это намеренная цена
  отказа от неявного merge;
- Git review рабочей версии исчезает — компенсируется snapshot audit и export;
- слишком раннее удаление files лишит rollback — cleanup только после окна
  наблюдения и backup acceptance;
- попытка объединить UI и storage границы создаст новый god-document — архитектурная
  приёмка проверяет критерии границы документа.

## ADR

ADR обязателен и подготовлен:
`docs/adr/ADR-0048-typed-setting-documents-and-postgresql-runtime-state.md`.

Дополнительный ADR потребуется, если реализация предложит:

- Redis/pub-sub или новый runtime-сервис;
- хранение секретов в портальной БД;
- изменение AG-UI/CopilotKit версии или wire contract;
- перенос knowledge canon/runtime skills в PostgreSQL;
- постоянную multi-backend запись вместо cutover;
- новый внешний публичный API конфигурации.
