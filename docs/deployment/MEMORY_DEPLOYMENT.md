# Развертывание и проверка системы памяти

## Назначение

Этот документ описывает, как включить и проверить memory service после обновления проекта. Общий production deploy описан в `docs/deployment/DEPLOYMENT.md`; здесь перечислены дополнительные шаги для памяти.

## Что добавляется

Код (после ADR-0030 packets 01-08):

- Django app `apps.memory` (канон + reconciler + единая очередь + ревью через git + словарь рёбер + заглушки data store) и `apps.filehub` (замороженное автоупорядочивание файлов, вынесено из `apps.memory`);
- контракты `contracts/ai/memory_sources.json`, `memory_profiles.json`, `memory_routing.json`, `memory_trust_policy.json`, `memory_claims_policy.json`, `memory_retrieval_budget.json`, `memory_ingestion_profiles.json`, `memory_file_organization_profiles.json`, `memory_graph_schema.json` (контролируемый словарь типов рёбер для `relations:`, не LLM-схема);
- схемы `contracts/schemas/memory_*.schema.json`;
- AI tool `memory.search` — публичный контракт сокращен до `query`/`limit`/`sensitivity`/`corpus` (ADR-0030 решение 6); `search_mode`/`ranking_profile`/`include_source_data` отклоняются явной ошибкой;
- pull-reconciler `memory_reconcile` (`--dry-run`, `--force`) и сверка `memory_verify_knowledge_files`;
- management commands `memory_sync_source`, `memory_reindex`, `memory_eval`, `memory_export_knowledge_files`, `memory_migrate_legacy_knowledge`;
- фоновые команды над единой очередью `memory_queue_worker`, `knowledge_reflection_worker` (регенерация `index.md`/`log.md`, предложение кандидатов), `memory_file_backed_e2e`, `memory_file_content_search_e2e`;
- external connector commands `memory_external_enqueue`, `memory_external_worker`, `memory_external_queue_status`, `memory_external_cleanup` (та же таблица-очередь `MemoryExternalConnectorJob`, что и у остальных фоновых задач памяти);
- e2e acceptance-набор блока `memory_alignment_acceptance_e2e` (`apps/memory/management/commands/`).
- file source auto organization commands `memory_file_organization_baseline`, `memory_file_incoming_worker`, `memory_file_structure_stats`, `memory_file_move_worker`, `memory_file_auto_organization_e2e` — теперь в `apps.filehub.management.commands`, функционально не изменились, но приложение заморожено.

Выведенные команды (не существуют в коде после ADR-0030): `memory_graph_extract`, `memory_graph_schema_discover` (заменены словарем типов + валидатором `relations:` + `memory_reconcile`), `knowledge_writer_worker`, `knowledge_index_worker` (заменены синхронной записью `memory.remember` + `memory_reconcile`), `memory_reflect_chats` (обработка очереди ушла в прямую запись; ночная рефлексия — `knowledge_reflection_worker`).

Runtime data:

- `data/contracts/ai/` — runtime copies of AI/memory contracts;
- `data/knowledge_repo/` — runtime Git-репозиторий принятых знаний — **канон** (см. «Резервное копирование `data/knowledge_repo/`» ниже);
- основная PostgreSQL database — данные AI-чатов, metadata памяти (пересобираемая проекция канона), управляющие модели аналитики, единая очередь `MemoryExternalConnectorJob` и таблица рёбер `MemoryKnowledgeEdge`;
- PostgreSQL full-text таблица `MemoryFullTextIndex` — production индекс поиска по памяти;
- `data/db/*.sqlite3` — legacy/dev источники миграции, не production target основного репозитория;
- `data/indexes/` — generated dev/legacy SQLite FTS и vector indexes;
- `data/processing/` — временные raw/safe/extraction зоны;
- `data/memory/safe_corpus/` — legacy compatible safe text для старого ingestion слоя;
- `data/memory/manifests/` — manifests;
- `data/memory/external_api/` — normalized landing zone for external information system connectors;
- `data/memory/queues/` — dev/legacy standalone external connector queue backend;
- `data/memory/reconcile_state.json` — состояние reconciler (последний материализованный commit);
- `data/memory/eval/` — eval reports.

Эти runtime data не коммитятся в основной репозиторий кода, но `data/knowledge_repo/` — это отдельный git-репозиторий сам по себе (см. backup ниже).

## Перед деплоем

На staging или локально:

```bash
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests apps.memory.tests apps.ai.tests apps.analytics.tests
```

Ожидаемо:

- миграции не требуют генерации новых файлов;
- architecture contracts valid;
- тесты проходят.

## Production deploy

Обычный Docker deploy:

```bash
./deploy.sh
```

Production entrypoint выполняет:

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_roles
```

После деплоя обязательно проверить, что миграции применились до запуска memory commands. Если деплой не использует стандартный entrypoint, выполнить вручную:

```bash
python manage.py migrate --noinput
```

После первого обновления на раздельные базы выполнить перенос legacy-данных:

```bash
python manage.py migrate_legacy_chat_db --dry-run
python manage.py migrate_legacy_chat_db
python manage.py migrate_legacy_analytics_control_db --dry-run
python manage.py migrate_legacy_analytics_control_db
python manage.py memory_migrate_legacy_knowledge --dry-run
python manage.py memory_migrate_legacy_knowledge
python manage.py memory_verify_knowledge_files --strict
```

## Runtime contracts

При первом запуске settings копирует default contracts из `contracts/` в `data/contracts/`. Если в `data/contracts/ai/` уже были старые runtime-копии, они не перезаписываются автоматически.

После обновления с добавлением `memory.search` и memory contracts проверить:

```bash
python manage.py validate_architecture_contracts
```

Если команда падает из-за устаревших `data/contracts/ai/tools.json` или `task_types.json`, нужно синхронизировать runtime contracts с текущими default contracts контролируемым способом:

```bash
cp contracts/ai/tools.json data/contracts/ai/tools.json
cp contracts/ai/task_types.json data/contracts/ai/task_types.json
cp contracts/ai/memory_sources.json data/contracts/ai/memory_sources.json
cp contracts/ai/memory_profiles.json data/contracts/ai/memory_profiles.json
cp contracts/ai/memory_routing.json data/contracts/ai/memory_routing.json
cp contracts/ai/memory_trust_policy.json data/contracts/ai/memory_trust_policy.json
cp contracts/ai/memory_claims_policy.json data/contracts/ai/memory_claims_policy.json
cp contracts/ai/memory_retrieval_budget.json data/contracts/ai/memory_retrieval_budget.json
cp contracts/ai/memory_ingestion_profiles.json data/contracts/ai/memory_ingestion_profiles.json
cp contracts/ai/memory_file_organization_profiles.json data/contracts/ai/memory_file_organization_profiles.json
cp contracts/ai/memory_graph_schema.json data/contracts/ai/memory_graph_schema.json
python manage.py validate_architecture_contracts
```

На production перед копированием сохранить backup runtime contracts, если они редактировались через UI или вручную.

## Резервное копирование `data/knowledge_repo/` (канон)

`data/knowledge_repo/` — не обычные runtime data: это единственный источник истины для текста и метаданных знания (ADR-0030 решение 1). Потеря этого репозитория без резервной копии means потерю знания безвозвратно, даже если PostgreSQL-проекция (`MemoryKnowledgeItem`, FTS, `MemoryKnowledgeEdge`) цела — проекция без канона не пересобирается.

Обязательная политика (выбрать один вариант или оба):

1. **Удаленный git-репозиторий (предпочтительно).** `data/knowledge_repo/` — обычный git-репозиторий; добавить `remote` (приватный Git-хост или bare-репозиторий на резервном хранилище) и push после записи:

   ```bash
   git -C data/knowledge_repo remote add backup <url-приватного-репозитория>
   git -C data/knowledge_repo push backup --all
   ```

   Периодичность — не реже, чем допустимое окно потери данных для организации (RPO); минимум раз в сутки, для активно используемых порталов — после каждого крупного батча записи или по таймеру каждые 5-15 минут.

2. **Файловый backup.** Если удаленный git недоступен (изолированная сеть), делать снимок каталога целиком (включая `.git/`) на резервное хранилище стандартными средствами бэкапа хоста (тот же механизм, что и для `data/db/`, media и прочих runtime data). Файловый backup обязан включать `.git/`, иначе история и возможность `git filter-repo` (см. `docs/guides/MEMORY_USER_GUIDE.md`, «Мягкое удаление») будут потеряны вместе с рабочими файлами.

Восстановление: `git clone`/распаковка backup в `data/knowledge_repo/`, затем `python manage.py memory_reconcile --force` для полной пересборки проекции из восстановленного канона (без `--force` reconciler опирается на `reconcile_state.json`, который тоже может быть устаревшим после восстановления).

## Запуск reconciler: старт, таймер, после записи

`memory_reconcile` обязан выполняться в трех точках эксплуатации:

1. **При старте** приложения/деплоя (после `migrate`, до открытия трафика) — подхватывает любые ручные правки канона, сделанные пока сервис был выключен:

   ```bash
   python manage.py memory_reconcile
   ```

2. **По таймеру** (cron/systemd timer/планировщик Windows) — самовосстанавливающийся фоновый проход, ловит ручные правки файлов в рабочее время и любые пропущенные reindex-задачи единой очереди:

   ```bash
   */5 * * * *  cd /path/to/project && .venv/bin/python manage.py memory_reconcile
   ```

   Периодичность подбирается под допустимое окно рассинхронизации (concept v0.5 §7.1: мягкая деградация между правкой и reconcile, не ошибка) — 5 минут является разумной отправной точкой.

3. **После записи** — `memory.remember` уже индексирует инлайн в рамках синхронного вызова (см. `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`), поэтому отдельный `memory_reconcile` после каждой записи не обязателен для штатного пути. Он остается нужен после операций, которые меняют канон в обход `memory.remember`: прямая правка файла администратором/автором, `git pull` изменений с другого узла, восстановление из backup, ручное слияние pending-страницы через `/memory/review/pending/` (хотя `accept_pending_item`/`reject_pending_item` сами коммитят, дальнейший `memory_reconcile` подтверждает консистентность проекции).

Все три запуска идемпотентны и безопасны для параллельного администраторского вмешательства благодаря `knowledge_repo_lock`.

## Откат этапа 1 (file canon authoritative)

Флаг `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE` (по умолчанию `False`) переключает, какая сторона считается авторитетной на пути чтения:

- `False` (двойная работа) — проекция (`MemoryKnowledgeItem`) авторитетна, файл сверяется хэшем через `memory_verify_knowledge_files`;
- `True` — файл-канон авторитетен, проекция — пересобираемая производная.

Порядок включения (после чистой миграции):

1. Выполнить `python manage.py memory_verify_knowledge_files --strict` и убедиться, что расхождений нет.
2. Выполнить `python manage.py memory_reconcile` (без `--dry-run`), чтобы проекция была синхронизирована с последним состоянием канона.
3. Включить `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE=true` в конфигурации окружения и перезапустить сервис.

Порядок отката (если после включения обнаружена проблема):

1. Выключить `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE` обратно на `false` (вернуться к чтению из проекции) и перезапустить сервис — это единственный необходимый шаг для немедленного отката, поскольку код продолжает поддерживать оба режима чтения.
2. Если во время работы с `authoritative=true` были прямые правки канона, которые не попали в проекцию, выполнить `python manage.py memory_reconcile` перед откатом, чтобы не потерять эти изменения при возврате к чтению из БД.
3. Разобрать причину отката (обычно — расхождение, не пойманное `memory_verify_knowledge_files`) до повторного включения флага.

Флаг не меняет формат данных и не требует миграции схемы — откат не деструктивен.

## Windows/UNC ingestion

Ingestion-коннектор корпоративных документов проектируется для Windows Server в домене Active Directory. Подробные операторские правила: `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

Production checklist:

- подготовить отдельную read-only папку корпуса памяти;
- использовать UNC path вида `\\SERVER\Share\Folder`;
- не использовать mapped drives вроде `Z:\` для Windows services;
- запускать worker/Django service под учетной записью, которая реально имеет read-only доступ к UNC path;
- целевой вариант учетной записи - gMSA, допустимый стартовый вариант - обычный domain service account;
- не хранить SMB credentials, host-specific paths или service account secrets в default contracts и Git;
- оставить raw mode `reference_only`, пока отдельным решением не включен `quarantine_copy` или `immutable_raw_vault`;
- проверить, что encrypted/password-protected, partial и unsupported files создают review issues, а не пропадают молча.

Проверка доступа на Windows host под нужной учетной записью:

```powershell
whoami
Test-Path "\\SERVER\Share\Folder"
Get-ChildItem "\\SERVER\Share\Folder" -File | Select-Object -First 5
```

Если процесс работает как Windows service, проверку нужно выполнять в контексте той же service identity.

## Auto Organization Managed FS

Режим автоупорядочивания файлового источника включается отдельным runtime-контрактом:

```text
data/contracts/ai/memory_file_organization_profiles.json
```

Production checklist:

- применить миграции `knowledge_meta`, иначе таблицы `MemoryFileObject`, `MemoryFileVirtualPlacement`, `MemoryFileMoveJob` будут отсутствовать;
- задать `managed_root` в runtime contract или приватном deployment repo, не в default contract;
- создать входной каталог `<source>/incoming/new`;
- закрывать прямую запись в старые рабочие папки организационно или правами доступа, когда входной каталог принят пользователями;
- проверить `memory_file_organization_baseline --dry-run` и только потом запускать без `--dry-run`;
- запускать `memory_file_move_worker` только после администраторского решения по предложению структуры;
- хранить move manifests и карантин внутри runtime `managed_root`, а не в репозитории;
- запускать purge только после backup/snapshot checkpoint:

```bash
python manage.py memory_file_move_worker --source-code <code> --purge --backup-checkpoint-ref <snapshot-id>
```

Smoke:

```bash
python manage.py memory_file_auto_organization_e2e
```

Команда создает синтетический corpus в `.local/e2e/`, проверяет baseline, incoming, proposal, managed_fs copy/verify, quarantine и блокировку purge без backup checkpoint.

## External System Connector MVP

External information system connectors use normalized runtime envelopes and a queue backend selected by deployment profile.

Runtime paths:

```text
data/memory/external_api/
data/memory/queues/external_connectors.sqlite3  # только dev/legacy sqlite backend
```

Environment overrides:

```bash
# production PostgreSQL profile
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=database

# dev/legacy SQLite profile
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=sqlite
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=/path/to/data/memory/queues/external_connectors.sqlite3
```

В `DJANGO_ENV=production` SQLite-очередь запрещена без явного аварийного override
`LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION=true`.

MVP commands:

```bash
python manage.py memory_external_enqueue --source-code <source> --envelope-file <path> --dry-run
python manage.py memory_external_enqueue --source-code <source> --envelope-file <path>
python manage.py memory_external_queue_status
python manage.py memory_external_queue_status --details --limit 20
python manage.py memory_external_worker --limit 10
python manage.py memory_external_cleanup --source-code <source> --dry-run
```

`short_lived_raw_quarantine` may store raw API responses only when source config explicitly enables it and the raw response passes the DLP/secret gate. If credential material is detected, the raw payload is skipped and an issue is written to the landing zone. Source-system permissions are mapped manually into portal `scope_tokens` during each source implementation.

## Первичная настройка памяти

Проверить команды:

```bash
python manage.py memory_sync_source --help
python manage.py memory_discover_source --help
python manage.py memory_ingest_source --help
python manage.py memory_prepare_bootstrap_package --help
python manage.py memory_reconcile --help
python manage.py knowledge_reflection_worker --help
python manage.py memory_verify_knowledge_files --help
python manage.py memory_file_backed_e2e --help
python manage.py memory_file_content_search_e2e --help
python manage.py memory_file_organization_baseline --help
python manage.py memory_file_incoming_worker --help
python manage.py memory_file_structure_stats --help
python manage.py memory_file_move_worker --help
python manage.py memory_file_auto_organization_e2e --help
python manage.py memory_reindex --help
python manage.py memory_eval --help
python manage.py memory_alignment_acceptance_e2e --help
```

Синхронизировать источники:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_sync_source
```

Запустить smoke reindex:

```bash
# production PostgreSQL profile
LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND=postgresql

# dev/legacy SQLite profile
LOCAL_BUSINESS_MEMORY_FULLTEXT_BACKEND=sqlite_fts

python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py memory_reindex --corpus all --backend all
```

В `DJANGO_ENV=production` SQLite FTS запрещен без явного аварийного override
`LOCAL_BUSINESS_ALLOW_SQLITE_AUXILIARY_PRODUCTION=true`.

Запустить synthetic eval:

```bash
python manage.py memory_eval --dry-run
python manage.py memory_eval --output-json
```

Ожидаемый результат `memory_eval --dry-run`:

```text
Memory eval checks: passed=6, failed=0
```

Для ingestion MVP после синхронизации sources выполнить dry-run discovery/ingestion на выбранном источнике:

```bash
python manage.py memory_discover_source --source-code <code> --dry-run
python manage.py memory_ingest_source --source-code <code> --dry-run
```

Для памяти из AI-чата проверить прямую запись "запомни" (ADR-0030 решение 2, синхронный путь — очереди со `status=queued`/`job_id` на пути записи больше нет):

```bash
python manage.py memory_reconcile --dry-run
python manage.py knowledge_reflection_worker --dry-run
python manage.py knowledge_reflection_worker
```

`memory.remember` пишет файл знания и делает git commit синхронно, индексирует инлайн и сразу возвращает `memory_id`, `knowledge_file_path`, `knowledge_file_commit`, `index_status`. Проверить, что после вызова создан файл в `data/knowledge_repo/`, а `memory.search` находит сохраненное знание без дополнительного шага. `knowledge_reflection_worker` — ночная рефлексия (регенерация `index.md`/`log.md`, предложение кандидатов personal -> organization через pending-страницы), не обработчик очереди записи.

После проверки доступа, issue queue и ожидаемого количества файлов можно запускать без `--dry-run`:

```bash
python manage.py memory_discover_source --source-code <code>
python manage.py memory_ingest_source --source-code <code>
```

## Проверка после деплоя

Базовые проверки приложения:

```bash
curl -I http://<host>/health/
curl -I http://<host>/accounts/login/
```

Ожидаемо:

- `/health/` возвращает `200`;
- `/accounts/login/` возвращает `200`;
- `/` редиректит на login или dashboard.

Проверки Django внутри контейнера/виртуального окружения:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py memory_eval --dry-run
python manage.py memory_verify_knowledge_files --strict
python manage.py memory_file_backed_e2e
```

Проверки memory metadata:

```bash
python manage.py shell -c "from apps.memory.models import MemorySource, MemoryExternalConnectorJob, MemoryAccessAudit; print('sources', MemorySource.objects.count()); print('jobs', MemoryExternalConnectorJob.objects.count()); print('audits', MemoryAccessAudit.objects.count())"
```

Проверки AI tool registry:

```bash
python manage.py shell -c "from apps.ai.tool_definitions import get_tool_registry; print('memory.search' in get_tool_registry())"
```

Ожидаемо:

```text
True
```

## Проверка через UI

1. Войти staff/admin пользователем.
2. Открыть Django Admin.
3. Проверить наличие разделов `Memory sources`, `Memory search documents`, `Memory knowledge items`, `Memory index jobs`, `Memory access audits`.
4. Убедиться, что `MemorySearchDocument` показывает corpus, source, status и sensitivity, но не хранит и не раскрывает raw text.
5. Открыть AI-чат и выполнить запрос, который должен использовать память.
6. Проверить `MemoryAccessAudit`: после вызова `memory.search` появляется запись с `query_hash`, returned ids или denied reason.

Если поисковые документы еще не проиндексированы, AI-запрос может вернуть пустой результат. Это не ошибка деплоя, если audit запись создана и ошибок в логах нет.

## Troubleshooting

### `no such table: memory_memorysource`

Миграции не применены к runtime DB.

```bash
python manage.py migrate --noinput
```

### `validate_architecture_contracts` падает на `memory.search`

Runtime copy `data/contracts/ai/tools.json` или `task_types.json` устарела. Сравнить с default contract и синхронизировать после backup.

### `memory.search` возвращает пусто

Проверить:

- есть ли `MemorySearchDocument` со статусом `ready`;
- есть ли файл знания и корректный `knowledge_file_path` для `knowledge`-результатов;
- имеет ли источник `trust_status=trusted` и `trusted_for_context=true`;
- совпадает ли scope пользователя с `scope_tokens`;
- не запрошен ли слишком строгий `sensitivity`;
- есть ли запись в `MemoryAccessAudit`.

### `memory_eval --output-json` пишет не туда

Команда принимает только имя файла и принудительно пишет под `data/memory/eval/`. Пути вне этой директории должны отклоняться.

### В admin видны sensitive paths

Проверить `MemorySearchDocumentAdmin.search_fields` и list displays. `raw_path`, `safe_path`, `text_path` не должны быть searchable/displayed casually.

### UNC path недоступен из service

Проверить:

- используется ли UNC path, а не mapped drive;
- имеет ли service account read-only доступ к share и NTFS folder;
- запущен ли Django/worker именно под этой учетной записью;
- не лежат ли host-specific параметры в Git вместо приватного deployment repo.

### Документы индексируются частично

Это допустимое MVP-поведение для больших или сложных файлов. Нужно проверить, что:

- создан issue `partial_indexed`;
- citations показывают partial status/provenance;
- документ не представлен пользователю как полностью покрытый.
