# Текущее состояние MVP памяти

Дата: 2026-07-04.

Этот документ фиксирует фактическую рабочую границу системы памяти после блока выравнивания `memory-hybrid-knowledge-v05-alignment` (ADR-0030, packets 01-08). Целевые планы и ADR остаются источником решений "куда идем", но текущий runtime нужно сверять с этим описанием.

## Рабочий путь знания (ADR-0030)

### Запись

`memory.remember` пишет знание синхронно, в один вызов:

```text
memory.remember (actor, session, payload)
  -> права/политика источника
  -> write_knowledge_item_file() под кроссплатформенной блокировкой (knowledge_repo_lock)
  -> data/knowledge_repo/**/*.md (frontmatter + тело) + git commit
  -> index_knowledge_item() инлайн (MemoryKnowledgeItem + MemorySearchDocument + FTS/vector)
  -> ответ: memory_id, knowledge_file_path, knowledge_file_commit, index_status
```

Промежуточных таблиц-очередей на пути записи нет: `MemoryWriteRequest`, `MemoryIndexJob`, `MemoryKnowledgeEvent`, `MemoryReflectionRun` выведены. Если инлайн-индексация падает после успешной записи файла, в единую очередь `MemoryExternalConnectorJob` ставится retryable задача `reindex` (с dead-letter после исчерпания попыток) — сама запись при этом уже дурабельна.

Дисциплина одного писателя обеспечивается кроссплатформенной блокировкой `knowledge_repo_lock` (`apps/memory/knowledge_files.py`): `fcntl` на POSIX, `msvcrt` на Windows за одним интерфейсом (прежняя `fcntl`-only реализация была no-op на Windows — это устранено).

### Канон и pull-reconciler

Файл знания в `data/knowledge_repo/` — канон. Frontmatter несет только присущие знанию метаданные и workflow-флаг `lifecycle`; `index_status`, версии индексов и служебные хэши в канон не пишутся — они живут в проекции (`MemoryKnowledgeItem`).

`python manage.py memory_reconcile` (`--dry-run`, `--force`) — pull-reconciler:

- по content-hash гейту пересобирает проекции файлов, у которых изменилось содержимое или frontmatter-метаданные;
- идемпотентен: повторный запуск без изменений в файлах реконсилирует 0 знаний;
- ручная правка файла не ломает чтение (расхождение хэша больше не ошибка чтения);
- **не допускает молчаливого понижения классификации:** если ручная правка снижает `sensitivity`/`scope_tokens`, страница помечается `lifecycle: pending` (`pending_reason: classification_downgrade`) и держится на паузе до явного ревью; автоматическое движение метки — только вверх;
- перестраивает `index.md`/`log.md` из файлов и git-истории (не из БД-queryset);
- материализует рёбра графа из `relations:` (см. ниже) как безусловный шаг на каждом запуске, независимо от per-item content-hash гейта.

Авторитет файла-канона включается флагом `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE` (по умолчанию `False` — двойная работа: проекция авторитетна, хэши сверяются `memory_verify_knowledge_files`). Откат этапа 1 — выключить флаг обратно; порядок отката подробно описан в `docs/deployment/MEMORY_DEPLOYMENT.md`.

### Единая очередь

`MemoryExternalConnectorJob` — единственная таблица-очередь для фоновых задач памяти (reindex, reconcile-триггеры, ingestion, внешние коннекторы): `status`, `locked_by`/`locked_until`, `attempt_count`/`max_attempts`, `next_attempt_at`, `idempotency_key`, `priority`. Четыре прежние таблицы (`MemoryWriteRequest`, `MemoryIndexJob`, `MemoryKnowledgeEvent`, `MemoryReflectionRun`) удалены. `MemoryIngestionIssue` остается отдельной очередью проблем ingestion (issue queue), не сливается с задачной очередью.

### Ревью и кандидатство через git

Единый примитив изменений — `propose -> pending -> review -> stable`, реализованный на git-примитиве, а не на таблицах:

- кандидат personal -> organization — это страница в `org/` с `lifecycle: pending` в frontmatter (реальный файл + git-коммит), которую обычный `memory.search` не находит;
- понижение классификации ручной правкой (см. reconciler выше) точно так же превращается в `lifecycle: pending`;
- владелец знаний работает в `/memory/review/pending/`: принятие (`accept_pending_item`) переводит `lifecycle` в `current` и коммитит слияние — страница сразу доступна поиску; отклонение (`reject_pending_item`) фиксируется отдельным коммитом и никогда не индексируется;
- журнал ревью (`/memory/review/audit/`) — комбинированная лента из решенных issues, заданий единой очереди и git-истории `log.md`; таблиц `MemoryKnowledgeCandidate`/`MemoryReviewAction`/`MemoryKnowledgeEvent` в схеме больше нет.

### Рёбра графа: словарь типов + детерминированный материализатор

LLM graph-extraction контур (`MemoryGraphEntity`, `MemoryGraphExtractionRun`, `MemoryGraphSchemaProposal`, `MemoryGraphReviewItem`, команды `memory_graph_extract`, `memory_graph_schema_discover`) удален из кода.

Взамен:

- агент (при синтезе знания) может объявить рёбра в блоке `relations:` frontmatter: `{type, target, provenance}`;
- `apps/memory/knowledge_edges.py`: `validate_relation_entry`/`validate_relations_block` проверяют каждую запись против контролируемого словаря типов из `contracts/ai/memory_graph_schema.json` (`relation_types` со `status: accepted`; `proposed`/`rejected`/`deprecated` существуют для процесса расширения словаря, но не проходят валидатор); `target` должен быть путем файла знания или `knowledge_id` без пробелов; `provenance` — immutable-источник в форме `kind:locator`;
- `materialize_knowledge_edges()` детерминированно (без LLM) пересобирает таблицу `MemoryKnowledgeEdge` из всех файлов знаний при каждом `memory_reconcile`; идемпотентен (ключ `source_path, edge_type, target`); битые/невалидные записи попадают в `skipped` и не блокируют остальной репозиторий; ссылка на еще не существующую страницу материализуется с пустым `target_path`/`target_knowledge_id` (мягкая деградация, не ошибка);
- пока агент не эмитит `relations:`, графа нет — это не выключенный контур, а честное отсутствие данных; graph runtime search в `memory.search` остается вне MVP.

### Файловый контур — заморожен, вынесен

File Source Auto Organization (stable file identity, версии, baseline virtual structure, incoming worker, `/memory/files/`, managed_fs copy/verify/quarantine и т.д.) вынесен из `apps.memory` в отдельное приложение `apps.filehub` (`apps/filehub/`, `AppConfig.verbose_name = "Автоупорядочивание файлов (заморожено)"`). Функционально контур не изменился — команды `memory_file_organization_baseline`, `memory_file_incoming_worker`, `memory_file_structure_stats`, `memory_file_move_worker`, `memory_file_auto_organization_e2e` работают как раньше, просто зарегистрированы в `apps.filehub.management.commands`. Контур заморожен: новые функции не разрабатываются до выбора реального пилотного источника и явного решения владельца (ADR-0025 остается принятым, но замороженным).

### Один профиль ранжирования

`memory.search` больше не принимает `search_mode`/`ranking_profile`/`include_source_data`/сырые веса каналов — Django-шлюз (`apps/ai/tooling.py`, `_MEMORY_SEARCH_REMOVED_KEYS`) явно отклоняет их `ValidationError`, а не молча игнорирует. Публичный контракт (`contracts/ai/tools.json`, `apps/ai/tool_definitions.py`) сокращен до `query`, `limit`, `sensitivity`, `corpus` (`knowledge` по умолчанию | `source_data`). В runtime всегда действует один серверный профиль по умолчанию — гибрид FTS + вектор со слиянием RRF; точка расширения на будущее — `_select_ranking_profile()` в `apps/memory/retrieval.py`. Концепция профилей ранжирования ADR-0016 не отменена, а зафиксирована как отложенный архитектурный долг (backlog `Later`), возврат к ней — только после того, как `memory_eval` на реальном корпусе покажет измеримую пользу дифференциации.

Внутренние вызовы (`workorders.search` -> `memory.search`) по-прежнему используют старые именованные параметры (`search_mode="source_explicit"`, `ranking_profile="source_content"`) напрямую через `apps.memory.retrieval.memory_search()` в Python, минуя публичный gateway-контракт и его reject-список — это внутренний вызов между доверенными модулями, а не публичный API поверхности ИИ-бота.

Агент-рантайм (`services/agent_runtime/tools.py`, `services/agent_runtime/prompting.py`) реализует ту же публичную схему `query/limit/sensitivity/corpus`, чтобы LLM не могла отправить отклоняемые параметры.

### Заглушки data store (управляемый долг, этапы 5а/5б)

`apps/memory/data_store.py` определяет типизированный интерфейс `capture(dataset, observation)` / `query_dataset(dataset, query_name, params)`, поднимающий `NotImplementedError` до старта этапа 5а. Маркеры `# DEBT(ADR-0030-5a): ...` расставлены в точке маршрутизации `memory.remember` (`apps/memory/chat_memory.py`) и в `memory_reconcile` (`apps/memory/management/commands/memory_reconcile.py`) как места будущей интеграции. Пока: каждое "запомни" становится файлом знания (вики — и есть staging), реестр датасетов не материализуется. Debt-записи 5а/5б зафиксированы в `docs/planning/backlog.md` (`Later`).

## Что работает

- Прямая синхронная запись `memory.remember` (файл + git commit + инлайн-индекс за один вызов) с fallback-переиндексацией через единую очередь при сбое инлайн-индексации.
- Pull-reconciler `memory_reconcile`: идемпотентная пересборка проекций из канона, guard против понижения классификации, генерация `index.md`/`log.md` из файлов/git, материализация рёбер.
- Персональные и организационные знания из AI-чата; кандидатство personal -> organization через pending-страницы и git-ревью.
- Мягкое удаление (`status: deleted`, текст остается в git-истории); настоящее стирание — административный runbook `git filter-repo` (`docs/guides/MEMORY_USER_GUIDE.md`).
- Secret handles: секретное значение не пишется в знание, индекс, audit и результат поиска.
- Runtime Git-репозиторий знаний `data/knowledge_repo/`.
- Единая основная БД для chat, memory metadata, аналитики и очереди/FTS-проекций памяти; production target — PostgreSQL.
- Единый профиль поиска (RRF) через `memory.search` по корпусам `knowledge`/`source_data`.
- Явный и fallback-показ `source_data` как ссылок на исходные объекты.
- Trusted-only gate для обычного контекста агента.
- `MemoryAccessAudit` для разрешенных и запрещенных поисков.
- Ingestion MVP для local/UNC источников, текстовых файлов и табличных `.csv/.tsv/.xlsx/.xls` с issue queue.
- PostgreSQL full-text backend в production; SQLite FTS5 остается dev/legacy fallback.
- LanceDB vector backend с локальным embedding provider; production-профиль включается через `LOCAL_BUSINESS_MEMORY_EMBEDDING_PROFILE`.
- Документный индекс: результат поиска возвращает документ, а не раздел/фрагмент.
- Словарь типов рёбер (`contracts/ai/memory_graph_schema.json`) + валидатор `relations:` + детерминированный материализатор `MemoryKnowledgeEdge`, вызываемый из `memory_reconcile`.
- Автоупорядочивание файлового источника как отдельное замороженное приложение `apps.filehub`: stable `MemoryFileObject`, версии, baseline virtual structure, incoming worker, пользовательский UI `/memory/files/`, managed_fs copy/verify/quarantine, блокировка purge без backup checkpoint.
- Reference implementation внешнего коннектора: envelope, database/sqlite queue backends (тот же `MemoryExternalConnectorJob`), landing zone, retention cleanup и handoff.
- Универсальные source adapters для внутренних модулей: `workorders` и `waiting_list` отдают `SourceObjectEnvelope`; `source_adapter_reconcile` строит проекции.
- Заглушки data store (`apps/memory/data_store.py`) и DEBT-маркеры для этапов 5а/5б.

## Что не работает как runtime MVP

- Graph runtime search в `memory.search` (рёбра материализуются, но не участвуют в ранжировании поиска).
- Дифференциация профилей ранжирования ADR-0016 (`precise`/`balanced`/`semantic_heavy`/`source_content`/`source_semantic`/`graph_future`) — управляемый долг, не подключена к runtime.
- Data store (append-only observations, типизированный `capture`/`query`) — этапы 5а/5б, только заглушки.
- OCR изображений и сканов.
- Фрагментный поиск по крупным разделам документа.
- Production parser cascade для PDF/DOC/DOCX и OCR.
- Production multilingual embedding model не скачивается и не включается автоматически.
- Claim/belief lifecycle.
- MLflow/Ragas/DeepEval quality tracing.
- Source-specific production connector для внешней ИС.
- Внешний HTTP API памяти.
- S3/S3-compatible backend для файлового автоупорядочивания.
- Автоматическое физическое перемещение файлов без администраторского согласования.
- Развитие File Source Auto Organization за пределы уже реализованного (контур заморожен).

Эти контуры не удалены из ADR и долгосрочных планов, но в текущем runtime они должны отображаться как `planned`, `disabled` или `not_ready`.

## `knowledge` и `source_data`

`knowledge` — это принятое знание. Обычный ответ агента должен опираться именно на этот корпус.

`source_data` — это исходные объекты и ссылки на них: файлы, API envelopes, документы источников. Они могут быть найдены явно (`corpus=source_data`) или как fallback, но результат `source_data` не является принятым знанием и должен показываться с предупреждением.

Система не должна записывать полный извлеченный текст исходного файла в `MemorySearchDocument.metadata`.

## `data/memory/chat_knowledge/`

`data/memory/chat_knowledge/` оставлен только как legacy append-only event log для событий памяти из чата.

Он не является источником истины для текста знания. Канонический текст знания находится в `data/knowledge_repo/`, а пересобираемая проекция метаданных — в `MemoryKnowledgeItem`.

## External connector

Generic external connector MVP считается reference implementation. Его можно использовать для тестов и подготовки pilot, но развитие source-specific adapter и production sync начинается только после выбора pilot source, владельца данных, правил доступа, sensitivity и retention. Очередь коннектора — та же таблица `MemoryExternalConnectorJob`, что и у остальных фоновых задач памяти.

## Проверки текущей границы

Базовые проверки:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reconcile --dry-run
python manage.py memory_verify_knowledge_files
python manage.py memory_alignment_acceptance_e2e
python manage.py memory_eval --dry-run
python manage.py memory_file_backed_e2e
python manage.py memory_file_content_search_e2e
python manage.py memory_file_auto_organization_e2e
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py source_adapter_reconcile --source-code workorders --target all --backend fulltext --dry-run
python manage.py source_adapter_reconcile --source-code waiting_list --target all --backend fulltext --dry-run
```

Документация, backlog и workflow должны отличать эту рабочую границу от будущих этапов fragment search, graph runtime search, data store (5а/5б), OCR, claim/belief и MLflow.
