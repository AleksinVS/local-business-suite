# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

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

## Next

### Профили гибридного ранжирования памяти и подсказки ИИ-бота

FTS5 и LanceDB уже подключены, но гибридное ранжирование пока не нормализует BM25/vector score как разные шкалы. Следующий этап — ввести серверные профили ранжирования, включить semantic search по исходным файлам через локальные embeddings и закрепить, как ИИ-бот выбирает режим поиска по намерению пользователя.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0016-memory-hybrid-ranking-profiles.md`;
- активный план находится в `docs/planning/active/memory-hybrid-ranking-profiles-and-agent-prompts.md`;
- workflow package находится в `workflow/active/memory-hybrid-ranking-profiles/`.

Предварительный scope:
- добавить `ranking_profile` в `memory.search` и agent runtime wrapper;
- заменить сложение raw score на RRF-based fusion;
- включить LanceDB retrieval для `source_data` в явных source-режимах без нового внешнего API;
- добавить правила: секрет блокирует индексирование документа и ставит blocker issue; PII индексируется, но ставится в audit queue;
- реализовать reindex/delete по `document_id` с delete+upsert для LanceDB;
- добавить trace с профилем, весами, RRF-позициями и итоговым score;
- уточнить системные подсказки ИИ-бота для `source_explicit`, `knowledge_semantic`, `knowledge_precise`, `source_fallback`;
- покрыть `precise`, `balanced`, `semantic_heavy`, `source_content` и `source_semantic` e2e-тестами.

Критерии готовности к старту:
- подтверждено, что MVP использует RRF, а не min-max как основной fusion;
- подтверждено, что source semantic search входит в ближайший scope без нового внешнего API и cloud embeddings;
- согласованы тексты подсказок ИИ-бота.

### Поиск по крупным разделам документов

FTS5 и LanceDB по документу целиком реализованы. Следующий отдельный этап — перейти от документного результата к крупным разделам/листам/диапазонам строк без возврата старой модели `MemoryChunk`.

Контекст:
- архитектурное решение находится в `docs/adr/ADR-0015-file-content-fts-vector-search.md`;
- архивный план реализованного среза находится в `docs/planning/archive/2026/memory-file-content-fts-and-vector-search.md`;
- предварительно рекомендованный вариант — `MemorySearchSegment` в Django без хранения полного текста.

### Pilot adapter внешней информационной системы

Generic external connector MVP архивирован как reference implementation. Следующий шаг возможен только после выбора первой внешней системы.

Критерии готовности к старту:
- выбран pilot source и владелец данных;
- заполнены опросники из `docs/guides/MEMORY_EXTERNAL_SYSTEMS_QUESTIONNAIRES.md`;
- утверждены sensitivity, scope mapping и retention;
- подтвержден способ синхронизации: delta API, `updated_at`, webhook+reconciliation или scheduled full sync.

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

### Graph runtime search

Graph schema bootstrapping и extraction-команды остаются подготовительным контуром. Возврат graph facts через `memory.search` не включен в MVP и требует отдельной стратегии индекса, прав, provenance и ранжирования.

### Claim/belief governance

`MemoryClaim`/`MemoryBelief` не входят в текущую MVP-схему и обычный путь `memory.remember`/`memory.search`. Возвращаться к этому слою стоит только после появления реальных противоречивых источников и процесса review.

### MLflow quality tracing

Черновой план MLflow архивирован. Контур качества можно вернуть в работу после стабилизации поиска по содержимому и отдельного решения по безопасной записи trace без секретов и необезличенных персональных данных.

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
