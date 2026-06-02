# Операционный guide: memory ingestion и graph schema bootstrapping

## Назначение

Этот guide описывает, как людям и агентам внедрять и эксплуатировать ingestion корпоративных документов и bootstrapping схемы графа памяти. Архитектурные решения зафиксированы в:

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`.

Документ не разрешает менять `apps/` или `contracts/` в обход отдельного task packet. Он фиксирует операторские правила, ограничения MVP и проверки.

## MVP Scope

В первый эксплуатационный контур входит:

- ingestion из локальной папки Windows Server или UNC path вида `\\SERVER\Share\Folder`;
- dedicated read-only corpus folder вместо сканирования всего корпоративного файлового хранилища;
- service account с read-only доступом, целевой production-вариант - gMSA;
- raw mode `reference_only`: хранить URI/path reference, hash, metadata, MIME type, size и timestamps, не копировать raw documents в `data/memory/`;
- parser/OCR cascade для PDF, DOC, DOCX, XLS, XLSX, scanned PDF и standalone images;
- OCR languages `rus+eng`;
- default max file size 100 MB;
- partial indexing для больших или сложных документов с явным issue/review flag;
- scope-based access через `scope_rule` из `MemorySource`;
- graph schema bootstrapping по подготовленному safe/de-identified corpus;
- автоматическое создание graph entities/facts только после принятия схемы и прохождения validation gates;
- selective review queue для ingestion issues, schema proposals и рискованных extraction exceptions.

В MVP не входит:

- mapped drives для Windows services;
- сканирование полного unmanaged corporate share;
- хранение SMB credentials в Django или contracts;
- наследование реальных файловых ACL как механизм доступа;
- копирование всех raw documents в `data/memory/raw_vault/`;
- обязательный human review для каждого GraphEntity/GraphFact;
- визуальный graph explorer или полноценный ontology editor;
- production cloud OCR/LLM для чувствительных документов;
- indexed extraction embedded images inside DOCX/PDF, если документ не обрабатывается как scan;
- обязательный ClamAV gate.

## Windows/UNC внедрение

Подготовка источника:

1. Создать отдельную read-only папку для корпуса памяти.
2. Не включать туда документы, которые еще не прошли организационный отбор.
3. Для SMB использовать UNC path, например `\\FILESERVER\MemoryCorpus\DepartmentA`.
4. Не использовать mapped drive letters вроде `Z:\`, потому что Windows service может их не видеть.
5. Выдать service account только read-only права на папку и, если возможно, на чтение ACL metadata для будущего этапа.

Учетная запись:

- стартовый вариант: обычный доменный service account, например `DOMAIN\svc_memory_ingest`;
- production hardening: gMSA, например `DOMAIN\gmsa-memory$`;
- пароль service account не хранить в `.env`, contracts, `data/contracts/` или документации репозитория;
- host-specific настройки хранить в приватном deployment repo под `deployments/<host>/`.

Проверки доступа на Windows host:

```powershell
whoami
Test-Path "\\FILESERVER\MemoryCorpus\DepartmentA"
Get-ChildItem "\\FILESERVER\MemoryCorpus\DepartmentA" -File | Select-Object -First 5
```

Если Django/worker запущен как service, проверять доступ нужно под той же учетной записью, под которой работает service.

## Настройка source contract

Default contracts лежат в `contracts/ai/`, runtime-копии - в `data/contracts/ai/`. На конкретном host обычно редактируется runtime-копия `data/contracts/ai/memory_sources.json`, потому что путь к папке является deployment-specific значением.

Минимальный пример local source:

```json
{
  "code": "corporate_memory_docs",
  "title": "Corporate memory documents",
  "description": "Dedicated read-only folder for long-term corporate memory ingestion.",
  "source_kind": "local_path",
  "domain": "corporate_docs",
  "owner": "knowledge_owner",
  "enabled": true,
  "sync_mode": "manual",
  "schedule": null,
  "source_ref": "D:\\MemoryCorpus",
  "scope_rule": "authenticated_user",
  "sensitivity": "internal",
  "pii_policy": "deidentify_before_index",
  "versioning_mode": "hard_active_soft_raw",
  "retention_policy": "default_internal",
  "extractor_profile": "project_docs_v1",
  "chunking_profile": "long_policy_doc_v1",
  "index_profiles": ["fulltext_default"],
  "ignore_patterns": ["**/~$*", "**/*.tmp"],
  "ingestion_profile": "corporate_docs_windows_v1"
}
```

Для UNC source заменить:

```json
{
  "source_kind": "unc_path",
  "source_ref": "\\\\FILESERVER\\MemoryCorpus\\DepartmentA",
  "ingestion_profile": "corporate_docs_unc_windows_v1"
}
```

После изменения runtime contract выполнить:

```bash
python manage.py validate_architecture_contracts
python manage.py memory_sync_source --dry-run
python manage.py memory_sync_source
```

## Запуск и проверки

Базовые проверки проекта:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
```

Текущие memory MVP команды:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_sync_source
python manage.py memory_discover_source --source-code <code> --dry-run
python manage.py memory_discover_source --source-code <code>
python manage.py memory_ingest_source --source-code <code> --dry-run
python manage.py memory_ingest_source --source-code <code>
python manage.py memory_prepare_bootstrap_package --source-code <code> --department <department> --dry-run
python manage.py memory_prepare_bootstrap_package --source-code <code> --department <department>
python manage.py memory_graph_schema_discover --package <package-json> --dry-run
python manage.py memory_graph_schema_discover --package <package-json>
python manage.py memory_graph_extract --source-code <code> --dry-run
python manage.py memory_graph_extract --source-code <code>
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py memory_reindex --corpus all --backend all
python manage.py memory_eval --dry-run
python manage.py memory_eval --output-json
```

Команды автоупорядочивания файлового источника:

```bash
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py memory_file_organization_baseline --source-code <code>
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py memory_file_incoming_worker --source-code <code>
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py memory_file_structure_stats --source-code <code>
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py memory_file_move_worker --source-code <code>
python manage.py memory_file_move_worker --source-code <code> --purge --backup-checkpoint-ref <snapshot-id>
python manage.py memory_file_auto_organization_e2e
```

Baseline и incoming не меняют физические файлы. `memory_file_move_worker` обрабатывает только согласованные задания переноса. `--purge` удаляет только карантинную копию исходника после retention и, если политика требует, после `backup-checkpoint-ref`.

Ожидаемый smoke-результат для synthetic eval:

```text
Memory eval checks: passed=4, failed=0
```

В текущем MVP parser cascade реализован как безопасный baseline: text-like файлы индексируются, а PDF/Office/images попадают в issue queue до подключения production parser/OCR backend. Это сознательное ограничение, чтобы не имитировать качество OCR/Docling/Tika без реальных зависимостей и тестового корпуса.

## Issue Queue

Issue/review queue нужна для исключений, а не для всего потока документов.

Рабочий UI находится по адресу:

```text
/memory/review/
```

Личные виртуальные файловые структуры доступны пользователям по адресу:

```text
/memory/files/
```

Основные разделы:

- `Сводка` — счетчики открытых issues, blocker/privacy cases и проблем состояния индекса;
- `Issues` — очередь `MemoryIngestionIssue` с фильтрами по статусу, severity, типу, источнику и группам проблем;
- `Индекс` — состояние `MemorySearchDocument`, FTS/vector metadata и действия reindex/delete stale;
- `Файлы` — baseline-размещения, предложения общей файловой структуры и задания переноса;
- `Журнал` — неизменяемые `MemoryReviewAction` для решений оператора.

UI использует `ReviewQueueItem` как read-only проекцию для списков. Постоянной таблицы `ReviewCase` в MVP нет: источником истины остаются `MemoryIngestionIssue`, `MemorySearchDocument` и `MemoryReviewAction`.

Типовые issue kinds:

- `encrypted_file` - password-protected или encrypted файл пропущен;
- `unsupported_format` - нет безопасного parser/OCR пути;
- `file_too_large` - превышен лимит и нет разрешенной partial strategy;
- `partial_indexed` - документ индексирован частично;
- `parser_timeout` - parser не уложился в лимит;
- `ocr_timeout` - OCR не уложился в лимит;
- `pii_blocked` - privacy gate заблокировал extracted text;
- `pii_audit` - PII найдена, документ проиндексирован, администратору нужна проверка;
- `secret_blocked` - найден secret/token/key;
- `acl_unresolved` - ACL metadata не удалось получить или интерпретировать;
- `schema_unknown_type` - найден неизвестный тип для схемы графа;
- `schema_unknown_relation` - найдена неизвестная связь;
- `canonicalization_conflict` - конфликт нормализации сущности.
- `index_failed` - документ не удалось переиндексировать;
- `index_stale` - metadata индекса устарела;
- `fts_missing` - FTS-запись отсутствует или версия неизвестна;
- `vector_missing` - vector-запись отсутствует или версия неизвестна;
- `source_deleted_index_left` - исходный объект исчез, но индексная запись еще требует очистки.

Статусы:

```text
open
acknowledged
needs_expert_review
resolved
ignored
```

Операторская модель:

- `open` просматривает оператор памяти или администратор;
- `acknowledged` означает, что issue увидели и он не блокирует остальной run;
- `needs_expert_review` используется для schema/extraction вопросов профильному эксперту;
- `resolved` ставится после исправления причины или после успешного повторного ingestion;
- `ignored` допустим только с понятной причиной, например устаревший файл или намеренно неподдерживаемый формат.

Password-protected, encrypted, partial и suspicious документы не должны тихо исчезать из процесса: они остаются видимыми в issue queue и audit.

## Автоупорядочивание файлового источника

Архитектурное решение: `docs/adr/ADR-0025-file-source-auto-organization.md`.

Runtime-профили настраиваются в:

```text
data/contracts/ai/memory_file_organization_profiles.json
```

Default-шаблон лежит в:

```text
contracts/ai/memory_file_organization_profiles.json
```

Обязательные параметры профиля:

- `source_code` — код `MemorySource`;
- `incoming_path` — относительный путь входного каталога, обычно `incoming/new`;
- `managed_root` — host-specific управляемый корень, задается в runtime contract или deployment silo;
- `physical_move_policy=approval_required`;
- `source_delete_policy.mode=quarantine_then_purge`;
- `source_delete_policy.retention_days`;
- `source_delete_policy.requires_backup_checkpoint`;
- `proposal_thresholds` — минимальные пороги для предложений общей структуры.

Рабочая последовательность:

```text
memory_discover_source
  -> memory_file_organization_baseline
  -> memory_file_incoming_worker
  -> memory_file_structure_stats
  -> admin proposal decision
  -> memory_file_move_worker
  -> quarantine retention
  -> memory_file_move_worker --purge --backup-checkpoint-ref <snapshot-id>
```

Правила безопасности:

- `relative_path` не используется как личность файла в контуре автоупорядочивания;
- `MemoryFileObject.file_id` связывает один и тот же файл после смены пути;
- baseline создает только виртуальные размещения и review issues;
- входной каталог блокирует текстовые файлы с найденными секретами до публикации размещения;
- пользовательские виртуальные структуры не дают право доступа к файлу;
- предложения общей структуры строятся из агрегированных сигналов и порогов, а не из одного пользователя;
- физический перенос создает managed copy, проверяет SHA-256 и размер, затем переносит исходник в карантин;
- окончательное удаление исходника запрещено до retention и backup checkpoint, если профиль требует checkpoint.

Правила операторских действий:

- `secret_blocked` нельзя принудительно индексировать через UI; оператор исправляет источник или инициирует повторную переиндексацию после устранения причины;
- `pii_audit` можно acknowledged/resolved, документ остается индексированным согласно локальной privacy-модели;
- reindex из UI создает `MemoryIndexJob`, а не меняет индекс напрямую из шаблона;
- delete stale удаляет FTS/vector записи через backend service и пишет `MemoryReviewAction`;
- комментарии и metadata в журнале проходят safe serializer: raw secrets, необезличенная PII, полный извлеченный текст и raw query не должны попадать в UI или журнал.

Минимальные роли:

- `memory_admin` — полный контур ревью и действий с индексом;
- `memory_auditor` — privacy/audit issues и безопасный просмотр;
- `memory_index_operator` — reindex/delete stale/retry failed index;
- `memory_observer` — только чтение безопасной очереди.

## Schema Review Queue

Graph schema bootstrapping работает с типами и правилами, а не с каждым конкретным фактом.

Stage A, initiation:

1. Выбрать process-diverse подразделение.
2. Подготовить curated document subset.
3. Согласовать competency questions.
4. Собрать safe/de-identified bootstrap package.
5. Сформировать proposals по entity types, relation types, attributes, canonicalization rules и forbidden/noisy patterns.
6. Передать delta профильному эксперту.
7. Передать итог владельцу графа для финального accept/edit/reject.
8. Accepted proposals становятся частью runtime/default `memory_graph_schema.json` через контролируемое изменение контракта.
9. Rejected proposals сохраняются как negative examples.

Stage B, working schema evolution:

- новые документы обрабатываются по принятой схеме;
- валидные concrete entities/facts создаются автоматически;
- unknown patterns, conflicts, noisy terms и coverage gaps собираются как proposals;
- periodic review выполняют профильные эксперты и владелец графа.

Каждый accepted graph fact обязан иметь provenance: source, object id, `document_id` или evidence position, schema version, extractor, confidence, scope tokens и sensitivity.

## Cloud/OCR ограничения

Cloud GLM-OCR или cloud LLM schema discovery разрешены только для специально подготовленного non-sensitive или pseudonymized test package.

Перед экспортом всегда блокировать или удалять:

- passwords, tokens, API keys, private keys, connection strings;
- patient data;
- secrets в screenshots и OCR output;
- unreviewed sensitive internal data.

Production GLM-OCR рассматривается как будущий local GPU OCR service, изолированный от основного Django process.

## Агентные правила

При работе над ingestion/bootstrapping агент обязан:

- не менять `apps/` или `contracts/` без отдельного разрешенного write scope;
- не создавать временные corpus dumps, parser logs или export packages в корне проекта;
- писать временные артефакты только в `.local/`, runtime eval - только в `data/memory/eval/`;
- не добавлять host-specific UNC paths, service account names или secrets в default contracts;
- при изменении структуры обновить соответствующие `.desc.json` и запустить `make gen-struct`;
- перед финалом проверить, не устарели ли README, AGENTS, deployment guide, planning и ADR references.
