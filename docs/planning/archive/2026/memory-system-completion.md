# План завершения системы памяти

Статус: active.

Дата: 2026-05-20.

## Цель

Довести систему памяти до целевого состояния, где работают:

- безопасный поиск `memory.search` по corporate/document memory;
- ingestion корпоративных документов с parser/OCR production backend;
- персональная и организационная память из AI-чата;
- queued `memory.remember`;
- sleep-time reflection;
- promotion кандидатов в общие знания через audit владельца базы/графа знаний;
- secret handles без попадания значений секретов в LLM, индексы и логи.

## Архитектурные источники

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`;
- `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/architecture/MEMORY_COMPLETION_GAP_ANALYSIS.md`;
- `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`.

## Scope

Включено:

- доработка memory contracts и AI tool registry;
- новые модели и сервисы `apps.memory`;
- файловые runtime projections в `data/memory/chat_knowledge/`;
- immediate queued remember path;
- scheduled reflection command;
- organization candidate review;
- unified secret handle interface;
- Vaultwarden-compatible external vault link as the preliminarily approved MVP storage for human-entered/human-read secrets;
- permission capabilities для personal/org/secret memory;
- admin visibility and audit;
- tests and eval suites.

Не включено:

- перенос памяти в отдельный network service;
- PostgreSQL как обязательная зависимость;
- production cloud OCR/LLM для sensitive данных;
- раскрытие secret values агенту или LLM;
- прямое индексирование всей истории чата без extraction pipeline.

## Этапы

### 1. Документация и ready package

- Зафиксировать ADR-0005.
- Зафиксировать gap analysis.
- Создать workflow-блок с task packets.
- Обновить backlog.

Acceptance:

- есть ADR, architecture plan, active planning и workflow packet;
- `PROJECT_STRUCTURE.yaml` обновлен.

### 2. Data model and storage

- Добавить `MemoryWriteRequest`, `MemoryKnowledgeItem`, `MemoryKnowledgeCandidate`, `MemoryReflectionRun`, `SecretHandle`, `SecretAccessAudit`.
- Добавить atomic writer для `data/memory/chat_knowledge/`.
- Добавить projections rebuild.

Acceptance:

- миграции проходят;
- append-only events и current projections пишутся атомарно;
- personal/org scopes не смешиваются.

### 3. `memory.remember`

- Добавить tool в `apps/ai/tool_definitions.py` и `contracts/ai/tools.json`.
- Добавить handler через service layer.
- Queue status возвращается пользователю.

Acceptance:

- explicit remember defaults to personal;
- org remember requires explicit target and permission;
- tool does not write directly to indexes.

### 4. Reflection

- Добавить `memory_reflect_chats`.
- Добавить locks, watermarks, idempotency.
- Добавить candidate promotion to organization memory.

Acceptance:

- reflection can run dry-run and real mode;
- repeated run does not duplicate facts;
- organization candidates require review.

### 5. Secret handles

- Добавить provider-neutral `SecretHandleBackend`.
- Добавить first provider mode.
- Переделать secret handling на span-level extraction.

Acceptance:

- secret value never appears in memory chunks, prompts, traces or logs;
- non-secret text around a secret continues through ingestion;
- agent returns only handle/link metadata.

### 6. Permissions, admin and UX

- Добавить capabilities.
- Добавить admin lists/actions.
- Добавить personal edit/delete through chat.

Acceptance:

- owner can edit/delete personal memory;
- knowledge owner can approve/reject candidates;
- unauthorized users cannot read another user's personal memory.

### 7. Eval and release

- Добавить chat memory eval suite.
- Добавить secret leakage tests.
- Обновить deployment/user guides.

Acceptance:

- `make check`;
- `make test` or scoped tests;
- `make contracts`;
- `memory_eval --dry-run`;
- no secret leakage in test fixtures.

## Open questions

Нет блокирующих вопросов. Имена permission capabilities можно уточнить при реализации, но модель прав уже задана этим планом.
