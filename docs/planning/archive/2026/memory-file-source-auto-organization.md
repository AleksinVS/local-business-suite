# Автоупорядочивание файловых источников

## Статус

MVP реализован 2026-06-02. Ожидает приемку владельцем и выбор реального пилотного файлового source.

Обновление 2026-07-04 (ADR-0030 решение 5, packet 04): контур вынесен из `apps.memory` в отдельное приложение `apps.filehub` без функциональных изменений и заморожен до выбора пилотного источника и явного решения владельца. Команды и маршруты ниже актуальны, но код живет в `apps/filehub/` (не `apps/memory/`).

Архитектурное решение: `docs/adr/ADR-0025-file-source-auto-organization.md`.

Проектный план: `docs/architecture/MEMORY_FILE_SOURCE_AUTO_ORGANIZATION_PLAN.md`.

Workflow-блок: `workflow/archive/2026/memory-file-source-auto-organization/`.

## Цель

Создать режим автоупорядочивания файлового источника, который сначала строит виртуальную структуру над исходным хранилищем, затем накапливает статистику использования, после этого предлагает физический перенос в управляемую структуру и оставляет путь к S3/S3-compatible storage backend.

## Фактически реализовано

- Stable file identity через `MemoryFileObject`, версии, физические размещения и path aliases.
- Contract/schema `memory_file_organization_profiles`.
- Baseline virtual structure generator с `confidence`, `evidence`, `conflicts` и review issues.
- Incoming worker для `<source>/incoming/new` с проверкой стабильности файла и secret blocking.
- User/system virtual views, пользовательский UI `/memory/files/`, usage events и aggregation-based organization proposals.
- Managed FS transfer: approved move jobs, copy, SHA-256/size verify, metadata commit, source quarantine и purge gate.
- Minimal UI `/memory/review/file-organization/`.
- Management commands:
  - `memory_file_organization_baseline`;
  - `memory_file_incoming_worker`;
  - `memory_file_structure_stats`;
  - `memory_file_move_worker`;
  - `memory_file_auto_organization_e2e`.

S3/S3-compatible backend не реализован как runtime-зависимость; интерфейс и модель хранения подготовлены через `storage_backend`/`storage_ref`.

## Пользовательская ценность

- Пользователь получает понятную структуру файлов без немедленного разрушения старого хранилища.
- Новые файлы попадают во входной каталог и не увеличивают старый хаос.
- Администратор видит объяснимую стартовую структуру, статистику и предложения.
- Физический перенос выполняется только после подтверждения, что структура работает.
- Хранилище можно постепенно очистить и сократить дубли.
- Будущий переход к S3 не потребует переписывать пользовательские представления.

## Принципы

1. Относительный путь не является идентификатором файла.
2. Физическое размещение и виртуальная структура разделены.
3. Первичная оптимальная виртуальная структура создается автоматически после анализа исходного хранилища.
4. Baseline structure является предложением, а не приказом к физическому переносу.
5. Входной каталог становится штатным путем добавления новых файлов.
6. Пользовательские виртуальные структуры собираются как агрегированный сигнал.
7. Физический перенос требует согласования, сверки и quarantine/retention.
8. Удаление исходника запрещено до copy/verify/metadata commit и backup checkpoint.
9. S3 остается future backend, но интерфейс хранения проектируется сразу.

## Не цели

- Не переносить файлы физически без накопленной статистики и approval.
- Не делать S3 обязательной зависимостью MVP.
- Не кодировать пользовательские виртуальные папки как S3 object keys.
- Не давать виртуальной структуре обходить ACL/scope-based access.
- Не хранить raw content или необезличенные PII в статистике использования.
- Не менять `apps/` или `contracts/` без отдельного task packet.
- Не сканировать полный unmanaged corporate share без подготовленного source scope.

## Целевая архитектура

```text
source local/UNC path
  -> discovery
  -> stable FileObject identity
  -> primary analysis
  -> generated baseline virtual structure
  -> incoming folder processing
  -> user virtual views
  -> usage statistics
  -> organization proposals
  -> admin approval
  -> managed_fs physical transfer
  -> quarantine and purge
  -> future S3 backend
```

## Исходная оптимальная виртуальная структура

Baseline создается после первичного анализа:

- учитывает текущие пути, имена, даты, типы документов, safe text, ACL, sensitivity и дубли;
- группирует файлы в объяснимые папки;
- помечает каждое размещение `confidence`, `evidence`, `conflicts`;
- отправляет спорные файлы в review;
- не меняет физические файлы;
- служит стартовой точкой для пользовательской оптимизации.

Критерий качества baseline: пользователь и администратор должны понимать, почему файл предложен именно в этот путь, и иметь возможность исправить правило.

## Путь к доказанной структуре

Система должна создавать предложения общей структуры не по одной эвристике, а по устойчивым сигналам:

- несколько пользователей независимо выбирают похожий путь;
- baseline placement часто принимается без исправлений;
- повторные перемещения редки;
- поиск и открытие файлов ускоряются;
- admin overrides не опровергают правило;
- нет конфликтов ACL или sensitivity;
- структура стабильна во времени.

Популярность сама по себе не достаточна: структура может быть привычной, но плохой. Поэтому proposal должен включать evidence, conflicts, confidence, affected files и rollback path.

## Этапы реализации

### Этап 1. Контракты и stable file identity

Статус: выполнено.

Задачи:

- принять ADR-0025;
- добавить `memory_file_organization_profiles.json` и schema;
- добавить модели stable identity, versions, physical placements и path history;
- обеспечить совместимость с существующими `MemorySourceObject` и `MemorySearchDocument`;
- добавить миграционный путь от path-based discovery к stable file identity для auto organization.

Проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests
```

### Этап 2. Baseline generator

Статус: выполнено.

Задачи:

- реализовать первичный анализ исходного хранилища;
- создать baseline virtual view;
- добавить dry-run и preview;
- создать review issues для low confidence и ACL/sensitivity conflicts.

Проверки:

```bash
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py test apps.memory.tests
```

### Этап 3. Incoming folder

Статус: выполнено.

Задачи:

- добавить входной каталог;
- обрабатывать только стабильные файлы;
- классифицировать файл;
- связывать файл со stable identity;
- предлагать virtual placement;
- блокировать публикацию при secret/ACL issues.

Проверки:

```bash
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py test apps.memory.tests
```

### Этап 4. User views и статистика

Статус: выполнено в MVP-объеме.

Задачи:

- добавить пользовательские виртуальные структуры;
- сохранять безопасные usage events;
- агрегировать статистику;
- формировать organization proposals;
- применить privacy threshold для персональных сигналов.

Проверки:

```bash
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py test apps.memory.tests apps.ai.tests
```

### Этап 5. Managed physical transfer

Статус: выполнено для `managed_fs`. S3-compatible backend остается future implementation.

Задачи:

- добавить `StorageBackend`;
- реализовать `managed_fs`;
- выполнять copy/verify/publish/quarantine/purge;
- обновлять metadata и индексы;
- не удалять исходник без retention и backup checkpoint.

Проверки:

```bash
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py test apps.memory.tests
```

### Этап 6. E2E, UI и операционная документация

Статус: выполнено в MVP-объеме.

Задачи:

- добавить UI baseline preview;
- добавить UI incoming/review;
- добавить UI proposals и move plan diff;
- добавить e2e на baseline, incoming, proposal, move и access control;
- обновить operator docs.

Проверки:

```bash
python manage.py memory_file_auto_organization_e2e
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
```

## Риски

| Риск | Снижение риска |
| --- | --- |
| Baseline окажется плохим | Показывать confidence/evidence, не переносить физически без статистики. |
| Пользователи продолжат писать в старые папки | Постепенно закрыть старые папки на запись, оставить incoming. |
| Перенос сломает ACL | Fail-closed, ACL verify, review issues. |
| Удаление исходника приведет к потере данных | Quarantine/retention, backup checkpoint, manifest, hash verify. |
| Популярная структура будет ошибочной | Учитывать churn, admin overrides, search success, conflicts. |
| Пользовательские сигналы раскроют личные интересы | Агрегация, privacy threshold, safe event serializer. |
| S3 будет внедрен преждевременно | Начать с `managed_fs`, но держать storage backend interface. |

## Definition of Ready

- ADR-0025 принят владельцем.
- Согласованы пилотный source, incoming path и managed root.
- Определены роли: `memory_organization_write`, `memory_organization_review`, observer.
- Уточнен срок retention для исходников после переноса.
- Уточнено, что является backup checkpoint.
- Подготовлен синтетический файловый corpus для e2e.
- Подтверждено, что code scope может менять `apps.memory`, `contracts/ai`, `contracts/schemas`, UI и tests.

## Definition of Done

- Stable file identity не зависит от relative path.
- Baseline virtual structure создается после primary analysis.
- Incoming folder обрабатывает новые файлы и отправляет спорные случаи в review.
- User virtual views работают без обхода прав.
- Usage statistics создает объяснимые organization proposals.
- Physical move работает через approval, copy, verify, metadata commit, quarantine и purge.
- Source purge невозможен без retention и backup checkpoint.
- Storage backend interface поддерживает future S3-compatible implementation.
- Unit и e2e проверки пройдены.
- README/AGENTS/architecture/deployment/guides/planning проверены на актуальность.
- `.desc.json` и `PROJECT_STRUCTURE.yaml` обновлены при изменении структуры.
