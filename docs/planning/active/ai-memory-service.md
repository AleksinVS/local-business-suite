# Активный план: сервис памяти СоСНА

Статус: Active.

Дата создания: 2026-05-19.

## Назначение

Этот файл является человекочитаемым планом реализации сервиса памяти в новой planning-системе проекта. Он не заменяет ADR и не является executor report.

Источники истины:

- архитектурное решение: `docs/adr/ADR-0003-ai-memory-service.md`;
- подробная архитектура и roadmap: `docs/architecture/MEMORY_SERVICE_IMPLEMENTATION_PLAN.md`;
- исполняемый workflow-блок: `workflow/active/block-ai-memory-service-2026-05-19/`;
- рабочая очередь: `docs/planning/backlog.md`.

## Почему нужен отдельный active plan

Сервис памяти затрагивает несколько критичных контуров:

- AI runtime и declared tools;
- contracts и runtime-копии в `data/contracts/`;
- security/privacy и деидентификацию пациентских данных;
- новые хранилища индексов в `data/memory/`;
- фоновые sync/reindex jobs;
- graph/vector/full-text retrieval;
- проверку RBAC и leakage.

По правилам planning-системы это больше одной небольшой правки, имеет повышенный риск и требует workflow-блока с task packets.

## Цель реализации

Добавить сервис памяти СоСНА, который:

1. Создает управляемый каталог memory sources через JSON-контракты.
2. Сохраняет immutable raw snapshots и safe/de-identified corpus в `data/memory/`.
3. Индексирует безопасные chunks в graph/vector/full-text backends.
4. Возвращает агенту контекст только через declared tool `memory.search`.
5. Применяет RBAC/scope filtering в backend и повторно в Django перед сборкой контекста.
6. Блокирует PII/secret leakage и запрещает cloud LLM route для чувствительных данных.

## Non-goals

Не входит в первый реализационный блок:

- миграция проекта на PostgreSQL;
- полноценный отдельный `services/memory_runtime`;
- подключение боевых Битрикс24/МИС/телефонии;
- визуализация графа;
- раскрытие или reverse lookup пациентских PII в AI runtime;
- cloud escalation для sensitive context.

## Implementation Tracks

### Track 1. Contracts Foundation

Цель: добавить memory contracts, JSON Schemas, settings-loading и validators.

Результат:

- `contracts/ai/memory_sources.json`;
- `contracts/ai/memory_profiles.json`;
- `contracts/ai/memory_routing.json`;
- schemas в `contracts/schemas/`;
- runtime-копирование в `data/contracts/ai/`;
- `validate_architecture_contracts` проверяет новый контур.

### Track 2. Backend Spikes

Цель: снять неопределенность перед тяжелой реализацией.

Проверить:

- LanceDB vs Qdrant для vector/full-text/hybrid retrieval;
- Kuzu graph schema и basic graph queries;
- Graphiti adapter viability with local LLM;
- local embeddings: `BAAI/bge-m3` и `intfloat/multilingual-e5-large`.

Результаты spike хранятся в `.local/` как временные отчеты или в `data/memory/eval/`, если они нужны runtime-оператору. В корень проекта отчеты не писать.

### Track 3. Django Memory App

Цель: создать `apps.memory` как контур метаданных, policies, selectors, services, admin и management commands.

Минимальные модели:

- `MemorySource`;
- `MemorySnapshot`;
- `MemoryChunk`;
- `MemoryGraphFact`;
- `MemoryIndexJob`;
- `MemoryAccessAudit`;
- `MemoryEvalCase`.

### Track 4. Privacy Pipeline

Цель: гарантировать, что индексируемый корпус безопасен.

Компоненты:

- structural de-identification;
- Presidio/custom recognizers;
- deterministic HMAC pseudonymization;
- CredentialGuard/DLP;
- blocked snapshot state;
- regression tests for PII/secret leakage.

### Track 5. Index Backends

Цель: включить graph/vector/full-text indexing.

Компоненты:

- `GraphMemoryBackend`;
- `KuzuGraphBackend`;
- `VectorMemoryBackend`;
- LanceDB or Qdrant implementation;
- idempotent upsert/deactivate by snapshot;
- index manifests.

### Track 6. Retrieval Tool

Цель: реализовать безопасный `memory.search`.

Компоненты:

- `SensitivityClassifier`;
- `ScopeTranslator`;
- `QueryPlanner`;
- graph/vector/full-text retrievers;
- RRF rank fusion;
- local reranker hook;
- `ContextAssembler`;
- `MemoryAccessAudit`;
- AI tool declaration and gateway integration.

### Track 7. Jobs, Evaluation, Admin

Цель: сделать сервис обслуживаемым.

Компоненты:

- `memory_discover_sources`;
- `memory_sync_source`;
- `memory_reindex`;
- `memory_eval`;
- admin actions;
- health checks;
- smoke/security evaluation suites.

## Реализационный порядок

1. Contracts Foundation.
2. Backend Spikes.
3. Django Memory App scaffold.
4. Raw Vault and safe corpus.
5. Privacy Pipeline.
6. Source adapters and chunking.
7. Graph MVP.
8. Vector/full-text MVP.
9. Retrieval Tool.
10. Jobs and evaluation.
11. Admin observability.

## Definition of Ready для первого coding-среза

Первый coding-срез готов к старту, когда:

- этот active plan принят;
- `workflow/active/block-ai-memory-service-2026-05-19/ARCHITECT_PLAN.json` создан;
- task packet `task-memory-contracts` содержит read/write scope и acceptance checks;
- ADR-0003 остается актуальным;
- нет незадокументированных архитектурных решений вне ADR.

## Definition of Done для блока

Блок считается завершенным, когда:

- все task packets имеют `EXECUTOR_REPORT.<task-id>.md`;
- все task packets имеют `TASK_ACCEPTANCE.<task-id>.md`;
- `make check`, `make test`, `make contracts` выполнены или причины пропуска явно указаны;
- security evaluation показывает нулевые утечки forbidden scope, PII и secrets;
- backlog очищен от завершенного активного блока;
- workflow-блок перенесен в `workflow/archive/2026/`;
- этот plan перенесен в `docs/planning/archive/2026/` или обновлен как следующий активный этап.

## Текущий следующий шаг

Начать с task packet:

- `workflow/active/block-ai-memory-service-2026-05-19/task-packets/task-memory-contracts.json`

Цель первого task packet: добавить memory contracts и validators без подключения индексов и без изменения agent runtime.

