# План: автоупорядочивание файловых источников

Статус: проектный план.

Дата: 2026-06-02.

Связанный ADR: `docs/adr/ADR-0025-file-source-auto-organization.md`.

Реализация MVP: выполнена 2026-06-02. В runtime добавлены stable file identity, baseline generator, incoming worker, пользовательский UI виртуальных структур, usage-driven proposals, managed_fs copy/verify/quarantine/purge gate, операторский UI и e2e-команда. S3-compatible backend остается future implementation.

## Назначение

План описывает целевую архитектуру режима автоупорядочивания файлового источника:

- сначала строится виртуальная структура над исходным хранилищем;
- после первичного анализа автоматически создается исходная оптимальная виртуальная структура;
- новые файлы попадают во входной каталог;
- система учится на пользовательских виртуальных структурах и фактическом поведении;
- физический перенос выполняется постепенно, только после статистического обоснования и согласования;
- исходные файлы удаляются только через безопасный quarantine/retention процесс;
- архитектура заранее совместима с будущим S3 или S3-совместимым backend.

План дополняет:

- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`;
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`;
- `docs/guides/WORKER_AND_QUEUE_OPERATIONS.md`.

## Проблема

Файловый источник часто содержит исторический хаос:

- разные отделы создавали разные папки;
- документы лежат по авторам, датам, проектам, контрагентам или случайным признакам;
- есть дубли, устаревшие версии и временные файлы;
- новые файлы продолжают попадать в старые места;
- пользователи хотят разные представления одной и той же коллекции.

Если сразу физически переложить файлы, можно получить новую ошибочную структуру. Если оставить только виртуальную структуру, физический хаос сохранится. Поэтому целевой путь:

```text
виртуальная структура
  -> статистика использования
  -> предложения общей структуры
  -> согласованный физический перенос
  -> optional S3 backend
```

## Целевые принципы

1. Путь не является личностью файла.
2. Физическое хранение и пользовательское представление разделены.
3. Исходная оптимальная структура создается автоматически, но остается предложением.
4. Физический перенос возможен только после review и понятного rollback.
5. Исходники удаляются только после copy/verify/metadata commit и retention.
6. Пользовательские виртуальные структуры используются как агрегированный сигнал.
7. Персональные действия пользователя не должны раскрывать чувствительные интересы другим пользователям.
8. S3 не вводится в MVP, но storage backend проектируется сразу.

## Целевая схема

```text
local/UNC source
  -> discovery
  -> stable FileObject identity
  -> primary analysis
  -> generated baseline virtual structure
  -> admin review and user use
  -> incoming folder processing
  -> usage statistics and learned proposals
  -> organization structure approval
  -> managed_fs physical move jobs
  -> source quarantine
  -> purge after retention
  -> optional S3 backend migration
```

## Слои системы

### File identity

Минимальная модель:

| Сущность | Назначение |
| --- | --- |
| `FileObject` | Стабильная карточка файла, не зависящая от текущего пути. |
| `FileObjectVersion` | Версия содержимого: hash, размер, источник, storage reference. |
| `FilePhysicalPlacement` | Текущее и историческое физическое размещение. |
| `FilePathAlias` | Старые пути и внешние ссылки, нужные для поиска и аудита. |

`file_id` создается при первом обнаружении. Если файл найден в другом месте с тем же hash/size и похожими metadata, система связывает его как дубликат или перемещение, а не как полностью новый объект.

### Virtual structures

Минимальная модель:

| Сущность | Назначение |
| --- | --- |
| `FileVirtualView` | Представление: baseline, organization, user, department, project. |
| `FileVirtualPlacement` | Размещение файла внутри virtual view. |
| `FileVirtualRule` | Правило размещения: classifier, template, manual pin, inherited rule. |
| `FileOrganizationProposal` | Предложение изменить общую структуру. |
| `FileOrganizationDecision` | Решение администратора. |

Виды представлений:

```text
baseline_auto
organization_candidate
organization_accepted
department_view
user_view
project_view
```

### Storage backend

Интерфейс:

```text
put(file_stream, expected_hash) -> storage_ref
verify(storage_ref, expected_hash, expected_size) -> result
copy_from_path(path, expected_hash) -> storage_ref
delete_or_quarantine(storage_ref, policy) -> result
open_read(storage_ref) -> stream
generate_access_link(storage_ref, user, ttl) -> link
```

MVP backend:

```text
managed_fs
```

Future backend:

```text
s3_compatible
```

Файлы в S3 не должны храниться по пользовательским путям. Рекомендуемый ключ:

```text
blobs/sha256/<first2>/<next2>/<sha256>
```

### Organization jobs

Новые фоновые задачи:

| Задача | Назначение |
| --- | --- |
| `organization_discovery` | Поиск файлов и обновление stable identity. |
| `baseline_build` | Генерация исходной оптимальной виртуальной структуры. |
| `incoming_classify` | Разбор входного каталога. |
| `proposal_build` | Создание предложений общей структуры из статистики. |
| `move_stage` | Копирование в managed root. |
| `move_verify` | Проверка hash/size/ACL. |
| `source_quarantine` | Карантин исходника после успешного переноса. |
| `source_purge` | Окончательное удаление после retention. |

Все задачи должны иметь idempotency key, безопасный retry и статус `needs_review` для спорных случаев.

## Исходная оптимальная виртуальная структура

### Назначение

Baseline нужен, чтобы пользователи и администратор не начинали с пустого экрана. Он создает первую объяснимую структуру после анализа исходного хранилища.

Baseline не является обязательной физической структурой. Это отправная точка для экспериментов и статистики.

### Сигналы для baseline

Файловые признаки:

- расширение и MIME type;
- размер;
- дата создания/изменения;
- имя файла;
- текущий относительный путь;
- частота изменений, если доступна;
- дубль по hash;
- похожесть имени и содержимого.

Содержательные признаки:

- тип документа;
- контрагент;
- проект;
- подразделение;
- период;
- оборудование;
- заявка;
- договор или финансовый документ;
- регламент, инструкция, отчет, акт, счет, письмо.

Управленческие признаки:

- source code;
- owner;
- sensitivity;
- scope tokens;
- ACL fingerprint;
- trust status;
- ошибки ingestion.

### Формат результата

Каждое размещение baseline должно иметь:

```json
{
  "file_id": "file_...",
  "virtual_path": "Договоры/2026/Поставщики/...",
  "confidence": 0.82,
  "evidence": [
    "file_name_contains_contract_number",
    "text_mentions_supplier",
    "mtime_year_2026",
    "source_path_mentions_procurement"
  ],
  "conflicts": [],
  "placement_source": "baseline_auto_v1",
  "review_required": false
}
```

Если confidence ниже порога или есть конфликт прав/чувствительности, файл попадает в `needs_review`.

### Ограничения baseline

Baseline не должен:

- менять физические файлы;
- удалять исходники;
- публиковать личные пользовательские правила;
- объединять файлы только по похожему имени без hash/metadata проверки;
- предлагать структуру, которая смешивает файлы с разными sensitivity или несовместимыми scope tokens.

## Входной каталог

Рекомендуемая структура:

```text
<source_root>/incoming/
  new/
  processing/
  needs_review/
  rejected/
```

Правила:

- пользователь кладет файлы в `incoming/new`;
- worker берет только стабильные файлы, не изменявшиеся `stable_after_seconds`;
- файл не публикуется, пока не создано виртуальное размещение;
- low confidence отправляется на review;
- прямой write в старые папки постепенно запрещается.

## Статистика виртуальных структур

Собирать:

- принятие baseline-предложений;
- ручные перемещения в user view;
- совпадение пользовательских путей у разных пользователей;
- число повторных перемещений одного файла;
- частоту поиска и открытия файла;
- долю успешных поисков после размещения;
- admin overrides;
- конфликтующие предложения;
- устаревшие или неиспользуемые ветки.

Не собирать в открытом виде:

- чувствительные личные названия папок;
- полный поисковый запрос пользователя;
- необезличенные PII из документов;
- raw content.

Для общей структуры использовать только агрегированные сигналы с минимальным числом пользователей/событий.

## Предложения общей структуры

Система создает `FileOrganizationProposal`, если:

- структура используется устойчиво;
- есть достаточное число независимых подтверждений;
- churn низкий;
- пользователи быстро находят файлы;
- нет unresolved ACL/sensitivity конфликтов;
- администраторские исправления не опровергают правило.

Пример proposal:

```text
Перенести документы типа "акт выполненных работ" в:
  Финансы/Акты/<год>/<контрагент>/

Основания:
  432 файла
  8 пользователей
  91% принятых baseline placements
  4 недели стабильности
  3 admin overrides
  нет ACL conflicts
```

Решения:

```text
accept_as_virtual_rule
accept_for_physical_move
edit
reject
needs_more_data
```

## Физический перенос

Физический перенос разрешен только для accepted proposal.

Состояния файла:

```text
source_active
move_planned
copy_staged
verified
managed_active
source_quarantined
source_purged
move_failed
needs_review
```

Безопасная операция:

```text
1. Считать source file metadata.
2. Проверить, что файл стабилен.
3. Скопировать в managed root с временным именем.
4. Сверить sha256 и size.
5. Атомарно опубликовать managed placement.
6. Обновить FileObjectVersion, FilePhysicalPlacement, MemorySourceObject и MemorySearchDocument.
7. Обновить индексы или поставить reindex job.
8. Переместить исходник в quarantine или поставить delete marker.
9. Удалить исходник после retention и backup checkpoint.
```

Ошибки ACL, hash mismatch, locked file, missing source и unexpected modification переводят задачу в `needs_review` или `failed`, а не продолжают удаление.

## Безопасность

Обязательные правила:

- fail-closed для ACL;
- secret scanning перед индексированием и перед записью в audit metadata;
- PII profile применяется по source policy;
- physical move не должен повышать доступность файла;
- пользовательские virtual views не дают права на файл сами по себе;
- доступ к файлу проверяется через source/placement policy;
- audit не пишет полный путь UNC, если он содержит чувствительные имена;
- delete/purge требует отдельного права `memory_organization_write` и audit action.

## UI

Минимальные экраны:

- baseline preview после первичного анализа;
- входной каталог и очередь `needs_review`;
- пользовательская виртуальная структура;
- сравнение user views и organization candidate;
- proposal review;
- physical move plan diff;
- move job status;
- quarantine/purge queue.

Пользователю показывать:

- личные виртуальные папки;
- принятые организационные папки;
- входной каталог;
- файлы, требующие его действия, если он владелец.

Администратору показывать:

- confidence и evidence;
- конфликты ACL/sensitivity;
- статистику принятия;
- прогноз затрагиваемых файлов;
- rollback/quarantine статус.

## Контракты

Добавить контракт:

```text
contracts/ai/memory_file_organization_profiles.json
contracts/schemas/memory_file_organization_profiles.schema.json
```

Минимальные поля:

```json
{
  "profiles": {
    "corporate_docs_auto_organization_v1": {
      "enabled": false,
      "source_code": "corporate_memory_docs",
      "incoming_path": "incoming/new",
      "managed_root": "data/runtime-placeholder/not-in-default-contract",
      "baseline_profile": "baseline_auto_v1",
      "physical_move_policy": "approval_required",
      "source_delete_policy": {
        "mode": "quarantine_then_purge",
        "retention_days": 30,
        "requires_backup_checkpoint": true
      },
      "storage_backend": "managed_fs",
      "future_backends": ["s3_compatible"]
    }
  }
}
```

Host-specific paths must live in runtime contracts under `data/contracts/` or deployment private repository, not in default contracts.

## Этапы реализации

### Этап 1. ADR, contracts и stable identity

Задачи:

- принять ADR-0025;
- добавить contract schema;
- добавить stable file identity модели;
- перестать использовать relative path как identity в auto organization path;
- добавить path history.

Проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests
```

### Этап 2. Baseline virtual structure

Задачи:

- реализовать primary analysis;
- создать baseline generator;
- добавить dry-run команду;
- создать preview в review UI или отдельном экране.

Проверки:

```bash
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py test apps.memory.tests
```

### Этап 3. Incoming folder

Задачи:

- добавить разбор входного каталога;
- проверять стабильность файла;
- связывать новый файл с `FileObject`;
- предлагать virtual placement;
- low confidence отправлять в review.

Проверки:

```bash
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py test apps.memory.tests
```

### Этап 4. User virtual views и статистика

Задачи:

- добавить пользовательские виртуальные папки;
- логировать безопасные usage events;
- добавить агрегатор статистики;
- создать proposals для общей структуры.

Проверки:

```bash
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py test apps.memory.tests apps.ai.tests
```

### Этап 5. Physical managed_fs move

Задачи:

- добавить `StorageBackend` и `managed_fs`;
- реализовать copy/verify/publish/quarantine/purge;
- добавить move jobs и статусы;
- добавить manifest;
- обновлять поисковые документы и индексы.

Проверки:

```bash
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py memory_verify_knowledge_files --strict
python manage.py test apps.memory.tests
```

### Этап 6. E2E и операционная приемка

Задачи:

- e2e: первичный baseline создается без физического изменения файлов;
- e2e: incoming файл получает virtual placement;
- e2e: accepted proposal запускает managed_fs copy/verify;
- e2e: исходник не удаляется до retention/backup checkpoint;
- e2e: пользовательская view не обходит права доступа.

Проверки:

```bash
python manage.py memory_file_auto_organization_e2e
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
```

## Definition of Done

- ADR-0025 принят.
- Есть contract/schema для organization profile.
- Файл имеет stable identity, не основанную на relative path.
- Baseline virtual structure создается после primary discovery.
- Incoming folder работает через worker и review queue.
- User virtual views не меняют права доступа.
- Statistics/proposals создаются из агрегированных сигналов.
- Physical move требует approval и выполняет copy/verify/metadata commit/quarantine.
- Source purge невозможен без retention и backup checkpoint.
- Managed fs backend реализован через StorageBackend interface.
- S3-compatible backend остается future implementation, но интерфейс покрыт тестами.
- Документация, `.desc.json` и `PROJECT_STRUCTURE.yaml` обновлены.
