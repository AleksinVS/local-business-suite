# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

### Файловые знания, раздельные базы и единый поиск

Спроектирован целевой переход памяти: принятые знания хранятся в runtime Git-репозитории, исходные данные остаются в источниках, метаданные и индексы вынесены в отдельные базы, поиск по знаниям и файловому хранилищу идет через единый сервис.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- проектный план находится в `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`;
- active planning находится в `docs/planning/active/memory-file-backed-knowledge.md`;
- workflow package находится в `workflow/active/memory-file-backed-knowledge/`.

Предварительный scope:
- добавить runtime Git-репозиторий знаний и формат файла знания;
- реализовать writer service с очередью, lock, temporary file, atomic rename и Git commit;
- реализовать reader service с проверкой прав;
- вынести metadata знаний, чаты и управляющие модели аналитики в отдельные базы;
- сделать единый search/index service для корпусов `knowledge` и `source_data`;
- заменить `MemorySnapshot`/`MemoryChunk` прямой индексной записью `MemorySearchDocument`;
- добавить degraded mode для `indexing_pending`;
- отделить ночную рефлексию от обработки записи;
- мигрировать существующие `MemoryKnowledgeItem` в файлы с проверкой хэшей.

Отдельный исполнительный блок по упрощению индексного слоя реализован и ожидает приемки/архивации:
- active planning находится в `docs/planning/active/memory-snapshot-chunk-removal.md`;
- workflow package находится в `workflow/active/memory-snapshot-chunk-removal/`.

### Trusted sources, claim/belief layer и lightweight retrieval

Первый срез реализован, MVP-граница синхронизирована через `ADR-0010`: `MemoryBelief` переносится на следующие этапы, а главным объектом сохраненного знания становится `MemoryKnowledgeItem`. В active backlog остаются будущие claim/belief governance и production hardening после MVP.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0009-trusted-memory-sources-claims-and-lightweight-retrieval.md`;
- проектный план находится в `docs/architecture/MEMORY_TRUSTED_SOURCES_CLAIMS_AND_RETRIEVAL_PLAN.md`;
- active planning находится в `docs/planning/active/memory-trusted-sources-claims-retrieval.md`;
- workflow package находится в `workflow/active/memory-trusted-sources-claims-retrieval/`.

Предварительный scope:
- добавить trust policy в контракты источников памяти;
- исключить `candidate_only`, `quarantined` и `blocked` источники из обычного `memory.search` context;
- добавить claim/belief lifecycle с evidence, contradictions, freshness и review;
- реализовать deterministic rank fusion/context packing без обязательного LLM rerank;
- добавить off-peak digest/reflection scoring и security eval для memory poisoning.

### Knowledge-driven business analytics

MVP vertical slice реализован: контракты аналитики, контрольные модели, fixture-first IMAP/email ingestion, общий extraction packet, дедупликация, пересчет метрик, reflection-кандидаты и AI diagnostics routing. В active backlog остается production hardening и подключение реальных источников.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`;
- проектный план находится в `docs/architecture/KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md`;
- операционный guide находится в `docs/guides/KNOWLEDGE_ANALYTICS_OPERATIONS.md`;
- active planning находится в `docs/planning/active/knowledge-driven-business-analytics.md`;
- workflow package находится в `workflow/active/knowledge-driven-business-analytics/`.

Оставшийся scope:
- подключить production IMAP/IDLE adapter с UIDVALIDITY/UID watermarks и секретами из deployment-среды;
- заменить JSONL fallback на Parquet/DuckDB после выбора runtime-зависимостей;
- подключить production queue backend для scheduled/polling jobs;
- добавить LLM/parser extraction backend вместо deterministic MVP extractor;
- реализовать optional DMS connector для выбранной системы документооборота;
- провести pilot tuning scope, retention, authority и dedup rules с владельцем данных.

### Сбор знаний из внешних информационных систем

Спроектировать и реализовать контур подключения внешних информационных систем к памяти через queued API-коннекторы, normalized landing zone и существующий memory ingestion.

Контекст:
- базовая архитектура памяти принята в `docs/adr/ADR-0003-ai-memory-service.md`;
- document ingestion и graph schema bootstrapping приняты в `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- архитектурное решение по внешним ИС находится в `docs/adr/ADR-0006-external-system-knowledge-connectors.md`;
- проектный план находится в `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_PLAN.md`;
- legacy gap review текущего vertical slice находится в `docs/architecture/MEMORY_EXTERNAL_SYSTEMS_CONNECTOR_GAP_REVIEW.md`;
- бизнес-опросники находятся в `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md`;
- active planning находится в `docs/planning/active/memory-external-systems-connector.md`;
- workflow package находится в `workflow/active/memory-external-systems-connector/`.

Предварительный scope:
- согласовать первую pilot-систему и заполнить опросники;
- добавить contracts/schema для external source connectors;
- реализовать durable queue с retries, idempotency и dead-letter;
- реализовать normalized landing zone с manifest/envelopes;
- сделать handoff в существующий memory ingestion;
- добавить retention, issue visibility, admin/tests и operations docs.
- закрыть legacy gaps перед подключением чувствительного production source: raw quarantine hardening, retention cleanup, manifest completeness, tombstones, worker dispatch для fetch/normalize stages, content hash verification.

Критерии готовности к старту реализации:
- выбран pilot source и владелец данных;
- подтвержден способ синхронизации: delta API, `updated_at`, webhook+reconciliation или scheduled full sync;
- утверждены sensitivity, scope mapping и retention;
- согласовано, что queue нужна с первого этапа;
- определено, можно ли ограничиться DB-backed queue для MVP.

## Next

### Система обезличивания данных и управляемые настройки

Черновик направления: реализовать контур обезличивания, управляемый контрактами, который включается постепенно по источникам, типам данных, целевым системам и этапам обработки.

Контекст:
- черновое архитектурное решение находится в `docs/adr/ADR-0012-data-anonymization-and-privacy-pipeline.md`;
- черновой план находится в `docs/planning/active/data-anonymization-privacy-pipeline.md`;
- связанный Settings Center план находится в `docs/planning/active/settings-center-gui.md`.

Предварительный scope:
- добавить контракт `contracts/privacy/anonymization_profiles.json` и JSON Schema;
- реализовать resolver маршрутов `source/type/target/stage -> profile`;
- включить MVP только на `before_cloud_llm` и `before_external_export`;
- добавить режимы `off`, `observe`, `warn`, `detect_and_redact`, `stable_pseudonym`, `review`, `block`;
- добавить audit без исходных PII/secret values;
- добавить dry-run/eval проверки;
- позже подключить Settings Center, Presidio-compatible adapter и privacy-worker.

Критерии готовности к старту:
- утверждены пилотные источники и целевые системы;
- согласован минимальный набор entity types;
- согласованы fallback-правила для внешних передач;
- подготовлен синтетический eval corpus;
- ADR и план переведены из черновика в принятое состояние.

### Production parser/OCR backend для ingestion памяти

Подключить production-grade parser/OCR cascade к уже реализованному ingestion MVP.

Контекст:
- архитектурное решение принято в `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- финальный план находится в `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- операторские правила находятся в `docs/guides/MEMORY_INGESTION_OPERATIONS.md`;
- ingestion MVP уже имеет discovery state, issue queue, local/UNC path adapter, graph schema contract и команды;
- текущий parser baseline индексирует text-like файлы, а PDF/Office/images отправляет в issue queue до подключения реального parser/OCR backend.

Предварительный scope:
- подключить и протестировать Docling/equivalent для PDF/DOCX/XLSX;
- подключить Tika/LibreOffice fallback для DOC/XLS;
- подключить OCR backend `rus+eng` для scans/images;
- формализовать GLM-OCR cloud test profile для подготовленной non-sensitive выборки;
- расширить parser quality eval на реальных тестовых документах;
- уточнить Excel limits после тестовой эксплуатации.

Критерии готовности к старту:
- создан workflow-блок и task packets для parser/OCR интеграции;
- определен первый read-only source folder и учетная запись сервиса для доступа;
- подтвержден UNC/local path deployment model без mapped drives;
- подготовлена безопасная тестовая выборка PDF/Office/scans;
- согласовано, какие документы можно отправлять в cloud GLM-OCR на тестах.

## Later

### Внешний API системы памяти

Спроектировать и реализовать полноценный внешний API для доступа сторонних сервисов к системе памяти. На текущем этапе не реализуем.

Контекст:
- текущая память не является отдельным сетевым сервисом: это Django app `apps.memory` внутри основного приложения;
- текущий внешний для agent-runtime путь доступа — Django AI gateway tool `memory.search`;
- прямой доступ сторонних сервисов к `data/memory/indexes/`, safe corpus или таблицам памяти запрещен;
- решение о стабильном внешнем API должно быть оформлено отдельным ADR до реализации.

Предварительный scope:
- HTTP API contract для поиска, citations, health/status и, при необходимости, ingestion requests;
- service identity и auth model для machine-to-machine доступа;
- RBAC/scope translation для сервисных учетных записей;
- rate limits, quotas и request tracing;
- обязательный `MemoryAccessAudit` для всех retrieval calls;
- запрет выдачи raw snapshots, raw paths, original PII и secrets;
- versioning API и backward compatibility policy;
- integration guide для новых сервисов;
- smoke/security tests и deployment checks.

Критерии готовности к старту:
- утвержден ADR;
- понятен первый внешний потребитель API;
- определены allowed operations: только retrieval или retrieval + managed ingestion;
- выбран механизм auth: gateway token, service accounts, mTLS или другой вариант;
- описаны форматы ошибок, citations и audit trace.

## Blocked

- Нет заблокированных задач.
