# Backlog

Актуальная очередь работ. Завершенные задачи здесь не хранятся: после завершения они удаляются из backlog, а итоговые планы и workflow-артефакты остаются в `docs/planning/archive/` и `workflow/archive/`.

## Active

### Долговременная память AI-блока

Добавить агенту долговременную память с пользовательским и организационным контурами доступа.

Контекст:
- архитектурное решение принято в `docs/adr/ADR-0003-ai-memory-service.md`;
- детальный проектный план находится в `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`;
- активный planning-файл: `docs/planning/active/ai-memory-service.md`;
- исполнительный workflow-блок: `workflow/active/block-ai-memory-service-2026-05-19/`;
- текущий первый task packet: `workflow/active/block-ai-memory-service-2026-05-19/task-packets/task-memory-contracts.json`.

## Next

- Нет ближайших кандидатов, зафиксированных в planning backlog.

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

### Методика работы с LLM в чате

Продумать контур сжатия контекста, суммаризации диалогов, смены заголовка после первой суммаризации и режимов заполнения памяти: оперативный режим и отложенный режим "сна" в ненагруженное время.

## Blocked

- Нет заблокированных задач.
