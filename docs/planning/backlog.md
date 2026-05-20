# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

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
