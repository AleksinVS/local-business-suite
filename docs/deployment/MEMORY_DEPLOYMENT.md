# Развертывание и проверка системы памяти

## Назначение

Этот документ описывает, как включить и проверить memory service после обновления проекта. Общий production deploy описан в `docs/deployment/DEPLOYMENT.md`; здесь перечислены дополнительные шаги для памяти.

## Что добавляется

Код:

- Django app `apps.memory`;
- контракты `contracts/ai/memory_sources.json`, `memory_profiles.json`, `memory_routing.json`, `memory_trust_policy.json`, `memory_claims_policy.json`, `memory_retrieval_budget.json`, `memory_ingestion_profiles.json`, `memory_graph_schema.json`;
- схемы `contracts/schemas/memory_*.schema.json`;
- AI tool `memory.search`;
- management commands `memory_sync_source`, `memory_reindex`, `memory_eval`;
- file-backed knowledge commands `knowledge_writer_worker`, `knowledge_index_worker`, `knowledge_reflection_worker`, `memory_verify_knowledge_files`, `memory_file_backed_e2e`;
- external connector commands `memory_external_enqueue`, `memory_external_worker`, `memory_external_queue_status`, `memory_external_cleanup`.

Runtime data:

- `data/contracts/ai/` — runtime copies of AI/memory contracts;
- `data/knowledge_repo/` — runtime Git-репозиторий принятых знаний;
- `data/db/chat.sqlite3` — данные AI-чатов;
- `data/db/knowledge_meta.sqlite3` — metadata памяти и знаний;
- `data/db/analytics_control.sqlite3` — управляющие модели аналитики;
- `data/indexes/` — generated indexes;
- `data/processing/` — временные raw/safe/extraction зоны;
- `data/memory/safe_corpus/` — legacy compatible safe text для старого ingestion слоя;
- `data/memory/manifests/` — manifests;
- `data/memory/external_api/` — normalized landing zone for external information system connectors;
- `data/memory/queues/` — standalone external connector queue backend;
- `data/memory/eval/` — eval reports.

Эти runtime data не коммитятся.

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
python manage.py migrate --database=default --noinput
python manage.py migrate --database=chat --noinput
python manage.py migrate --database=knowledge_meta --noinput
python manage.py migrate --database=analytics_control --noinput
python manage.py collectstatic --noinput
python manage.py seed_roles
```

После деплоя обязательно проверить, что миграции применились до запуска memory commands. Если деплой не использует стандартный entrypoint, выполнить вручную:

```bash
python manage.py migrate --database=default --noinput
python manage.py migrate --database=chat --noinput
python manage.py migrate --database=knowledge_meta --noinput
python manage.py migrate --database=analytics_control --noinput
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
cp contracts/ai/memory_graph_schema.json data/contracts/ai/memory_graph_schema.json
python manage.py validate_architecture_contracts
```

На production перед копированием сохранить backup runtime contracts, если они редактировались через UI или вручную.

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

## External System Connector MVP

External information system connectors use normalized runtime envelopes and a standalone queue backend.

Runtime paths:

```text
data/memory/external_api/
data/memory/queues/external_connectors.sqlite3
```

Environment overrides:

```bash
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=sqlite
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=/path/to/data/memory/queues/external_connectors.sqlite3
```

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
python manage.py memory_graph_schema_discover --help
python manage.py memory_graph_extract --help
python manage.py knowledge_writer_worker --help
python manage.py knowledge_index_worker --help
python manage.py knowledge_reflection_worker --help
python manage.py memory_verify_knowledge_files --help
python manage.py memory_file_backed_e2e --help
python manage.py memory_reflect_chats --help
python manage.py memory_reindex --help
python manage.py memory_eval --help
```

Синхронизировать источники:

```bash
python manage.py memory_sync_source --dry-run
python manage.py memory_sync_source
```

Запустить smoke reindex:

```bash
python manage.py memory_reindex --dry-run
python manage.py memory_reindex
```

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
python manage.py memory_graph_extract --source-code <code> --dry-run
```

Для памяти из AI-чата проверить обработку очереди "запомни".
`memory.remember` в обычном AI-инструменте возвращает `status=queued`, `request_id` и `job_id`;
`MemoryKnowledgeItem`, файл знания и поисковый индекс появляются после запуска writer worker.
`memory_reflect_chats` оставлен только как совместимый alias. Ночная рефлексия запускается отдельно:

```bash
python manage.py knowledge_writer_worker --dry-run
python manage.py knowledge_writer_worker
python manage.py knowledge_reflection_worker --dry-run
python manage.py memory_reflect_chats --dry-run
```

После запуска без `--dry-run` проверить, что запрос перешел в `accepted`, создан файл в `data/knowledge_repo/`, а `memory.search` находит сохраненное знание.

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
python manage.py shell -c "from apps.memory.models import MemorySource, MemoryIndexJob, MemoryAccessAudit; print('sources', MemorySource.objects.count()); print('jobs', MemoryIndexJob.objects.count()); print('audits', MemoryAccessAudit.objects.count())"
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
