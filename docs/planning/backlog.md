# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

### Завершение системы памяти: chat-derived memory, reflection и secret handles

Довести систему памяти до целевого состояния с персональной/организационной памятью из AI-чата, queued `memory.remember`, sleep-time reflection, candidate promotion и unified secret handles.

Контекст:
- базовая архитектура памяти принята в `docs/adr/ADR-0003-ai-memory-service.md`;
- ingestion документов принят в `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- chat-derived memory и secret handles приняты в `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`;
- gap analysis находится в `docs/architecture/MEMORY_COMPLETION_GAP_ANALYSIS.md`;
- implementation plan находится в `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`;
- active planning находится в `docs/planning/active/memory-system-completion.md`;
- workflow package находится в `workflow/active/memory-chat-reflection-secret-handles/`.

Предварительный scope:
- модели и atomic storage для `data/memory/chat_knowledge/`;
- `memory.remember` как write tool, который ставит ingestion request в очередь;
- scheduled `memory_reflect_chats`;
- organization knowledge candidates с review владельца базы/графа знаний;
- personal memory edit/delete через чат;
- provider-neutral `SecretHandleBackend`;
- span-level secret extraction вместо блокировки всего документа;
- permissions, admin visibility, eval и deployment/user docs.

Критерии готовности к завершению:
- explicit remember defaults to personal memory;
- organization write требует явного intent и permission;
- reflection-derived organization knowledge публикуется только после review;
- secret value не попадает в prompt/tool trace/index/log;
- non-secret text продолжает ingestion при наличии secret span;
- `python manage.py check`, `python manage.py validate_architecture_contracts`, scoped tests и `memory_eval --dry-run` проходят.

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
