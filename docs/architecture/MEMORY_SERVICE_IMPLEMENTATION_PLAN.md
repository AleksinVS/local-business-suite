# План реализации сервиса памяти СоСНА

Статус: проектный план.

Дата: 2026-05-19.

Цель: спроектировать и поэтапно реализовать локальный сервис памяти для AI-блока, который объединяет граф знаний, векторный поиск и полнотекстовый поиск, соблюдает RBAC, не раскрывает PII/секреты внешним LLM и вписывается в текущую архитектуру `local-business-suite`.

## Методологическая основа

Память AI-системы не должна быть просто "еще одним индексом". Это отдельный контур обработки знаний:

1. ELT/ingestion превращает исходные данные в проверяемые слепки.
2. Privacy/security слой решает, что можно индексировать и куда можно отправлять.
3. Индексы отвечают за разные виды поиска: векторный, полнотекстовый, графовый.
4. Retrieval orchestration собирает результаты, применяет права доступа, ранжирует и возвращает контекст с источниками.
5. Agent runtime использует память только через явный инструмент и не пишет напрямую в индексы или бизнес-БД.

Такой подход позволяет сразу добавить графы, но не потерять контроль над данными, аудитом и заменяемостью библиотек.

## Вводные решения

### Данные пациента

Пациентские данные могут попадать в память только после деидентификации:

- предпочтительный вариант: замена ФИО, телефона, адреса, ДР и иных PII на стабильные псевдонимы или внутренние ID;
- исходные PII не должны попадать в LLM prompt;
- индексируемый корпус должен хранить только безопасную версию текста;
- связь "реальный пациент -> псевдоним" остается в доменной БД или защищенном локальном хранилище, не в AI runtime.

### LLM routing

Режим смешанный:

- локальная LLM используется по умолчанию для чувствительных данных, граф-экстракции, PII-проверок и retrieval reasoning;
- облачная LLM допустима только после route gate, если запрос и контекст классифицированы как безопасные для внешней обработки;
- маршрутизация должна быть отдельным policy-layer, а не условием внутри промпта.

### PostgreSQL

PostgreSQL не вводится в MVP без необходимости.

MVP должен работать на текущей базе Django и файловых/embedded индексах:

- SQLite/Django ORM для системной метадаты;
- Raw Vault в `data/memory/`;
- Kuzu для графа;
- LanceDB или Qdrant для векторного индекса.

PostgreSQL остается вариантом развития, если появятся:

- высокая конкурентная запись;
- необходимость pgvector;
- единая SQL-операционность;
- сложные админские отчеты по памяти.

### Графы

Графы вводятся сразу, но через адаптерный слой.

Это означает:

- графовый backend должен быть заменяемым;
- доменная модель памяти не должна зависеть от конкретной библиотеки;
- графовые факты должны иметь provenance: source snapshot, chunk, hash, extractor version, timestamps.

### Секреты

Vaultwarden пока архитектурная идея. Для сервисных секретов предпочтительнее OpenBao как open-source secrets manager.

Vaultwarden/Bitwarden-подобный контур можно оставить для человеческих паролей и shared vault, но service-to-service секреты, API tokens, dynamic credentials и leases лучше проектировать вокруг OpenBao.

## Критическая оценка исходного предложения

### Что оставить

- Эволюционную стратегию: сначала узкий MVP, затем production-hardening.
- Raw Vault как обязательную основу воспроизводимости.
- Гранулярную синхронизацию по источникам и типам знаний.
- RBAC через scope tokens.
- PII/DLP до отправки данных в LLM.
- Разделение working/episodic/semantic memory, но с уточнением хранилищ.
- Soft versioning для отдельных типов знаний.

### Что изменить

- Не использовать `config/integrations/registry.json`; в проекте источник истины уже `contracts/integrations/registry.json`, runtime-копия в `data/contracts/integrations/registry.json`.
- Не хранить `.memignore` в корне. Правила discovery должны быть контрактом в `contracts/ai/memory_sources.json` или `contracts/ai/memory_rules.json`.
- Не выбирать Django Q: для Django 5.2 более надежный production-вариант - Celery + Redis + django-celery-beat; для простого локального режима допустим systemd timer/cron management commands.
- Не делать Redis источником Working Memory. В проекте уже есть `ChatSession` и `ChatMessage`; Redis нужен для cache/locks/broker.
- Не использовать NetworkX как production graph store. NetworkX можно применять только для offline analysis и тестов.
- Не делать LanceDB единственным enforcement-слоем RBAC. Scope-фильтрация должна применяться минимум дважды: при поиске в backend и перед сборкой контекста по авторитетной Django-метадате.
- Не удалять raw history при hard update. Можно деактивировать векторы/узлы, но raw snapshot и manifest нужны для аудита.

## Выбор стратегии: Cognee, Graphiti, LightRAG или свое ядро

### Рекомендация

Основной путь: собственное Memory Core с адаптерами.

Готовые OSS-компоненты нужно использовать выборочно:

- Kuzu как embedded graph DB;
- LanceDB или Qdrant как vector/hybrid store;
- Presidio как базовый PII analyzer/anonymizer с кастомными recognizer'ами;
- Graphiti как кандидат для graph extraction/retrieval adapter после spike;
- Cognee/LightRAG только как сравнительные прототипы, не как core dependency.

### Почему не Cognee как ядро

Cognee полезен как быстрый framework-based MVP: он умеет подключать LLM, embedding, relational DB, vector stores и graph stores. Но для этого проекта критичны:

- строгий RBAC;
- `data/contracts/` как runtime source of truth;
- атомарная запись контрактов;
- audit trail;
- маршрутизация local/cloud по чувствительности;
- запрет прямых write-path в бизнес-БД;
- деидентификация до индексации.

Если Cognee станет ядром, придется подстраивать эти требования под его модель. Это повышает риск lock-in и усложняет security review.

### Почему Graphiti стоит проверить

Graphiti лучше совпадает с требованием "графы сразу", потому что ориентирован на temporal context graph, provenance и hybrid retrieval. Важные ограничения:

- вокруг Graphiti все равно нужно строить свой governance, RBAC, source registry и UI;
- качественная ingest-экстракция зависит от structured output LLM;
- локальные небольшие модели могут давать нестабильные схемы;
- производительность и надежность нужно проверить на русскоязычных медицинских данных.

Решение: провести ограниченный spike и, если результат хороший, подключить Graphiti как `GraphMemoryBackend`, а не как владельца всего memory-service.

### Почему LightRAG не основной путь

LightRAG силен как end-to-end GraphRAG/RAG framework и быстро развивается. Но он больше похож на цельный RAG-продукт/сервер, а не на доменный компонент внутри Django-портала с контрактами, policy-first моделью и sensitive routing.

Решение: использовать как benchmark/prototype для сравнения retrieval quality, но не строить вокруг него архитектуру.

### Почему Mem0 не основной путь

Mem0 полезен для per-user agent memory. Для СоСНА нужен не только пользовательский профиль, а организационная база знаний, интеграционные слепки, медицинские регламенты, заявки, устройства, роли, аудит и scope-based access. Mem0 можно изучить для UI/API идей, но не как основной слой.

## Архитектурные решения

| Решение | Выбор | Причина |
| --- | --- | --- |
| Структура | Feature-first: отдельный Django app `apps.memory` и индексационный слой в `services/memory_runtime` или `apps.memory.services` | Не раздувать `apps.ai`, сохранить границы доменов |
| API | Внутренний Django service + declared AI tool `memory.search`; внешнего публичного API на MVP нет | AI runtime уже общается с Django через gateway |
| Auth/RBAC | Django session/policies + gateway token + Scope Translator | Django остается system of record |
| Background jobs | MVP: management commands/cron; production: Celery + Redis + django-celery-beat | Совместимо с Django 5.2 и управляемо |
| Storage | Raw Vault в `data/memory`, метаданные в Django DB, Kuzu graph, LanceDB/Qdrant vector/hybrid | Не требует PostgreSQL сразу |
| Realtime | Не нужен в MVP; достаточно scheduled sync и ручного reindex | Уменьшает сложность |
| Errors | Typed memory errors + audit log + retry state | Нужна диагностируемая эксплуатация |
| Secrets | OpenBao preferred для service secrets; Vaultwarden optional для человеческих vault-сценариев | OpenBao лучше подходит machine credentials и leases |

## Целевая структура в репозитории

Вариант MVP без нового отдельного сервиса:

```text
apps/
  memory/
    models.py
    policies.py
    selectors.py
    services.py
    ingestion.py
    deidentification.py
    retrieval.py
    routing.py
    graph_backends.py
    vector_backends.py
    management/commands/
      memory_discover_sources.py
      memory_sync_source.py
      memory_reindex.py
      memory_eval.py
contracts/
  ai/
    memory_sources.json
    memory_profiles.json
    memory_routing.json
  schemas/
    memory_sources.schema.json
    memory_profiles.schema.json
    memory_routing.schema.json
data/
  contracts/
    ai/
      memory_sources.json
      memory_profiles.json
      memory_routing.json
  memory/
    raw_vault/
    safe_corpus/
    indexes/
      lancedb/
      kuzu/
    manifests/
    eval/
```

Вариант развития с отдельным runtime:

```text
services/
  memory_runtime/
    app.py
    config.py
    ingestion_pipeline.py
    retrieval_pipeline.py
    graph/
    vector/
    schemas.py
```

Для MVP лучше начать с `apps.memory`, потому что:

- меньше операционной нагрузки;
- проще использовать Django ORM, settings, policies и management commands;
- проще тестировать;
- agent runtime уже может вызывать Django gateway.

Отдельный `services/memory_runtime` имеет смысл после стабилизации контрактов, когда появится тяжелая индексация, отдельный scaling profile или GPU-зависимые extractor jobs.

## Контракты памяти

### `contracts/ai/memory_sources.json`

Описывает, какие источники можно индексировать.

Пример структуры:

```json
[
  {
    "code": "workorders_public_timeline",
    "title": "История заявок без PII",
    "source_kind": "django_model",
    "domain": "workorders",
    "owner": "operations",
    "enabled": true,
    "sync_mode": "incremental",
    "schedule": "*/30 * * * *",
    "scope_rule": "workorder_visibility",
    "sensitivity": "internal",
    "pii_policy": "deidentify_before_index",
    "versioning_mode": "hard_active_soft_raw",
    "retention_policy": "default_internal",
    "extractor_profile": "workorder_v1",
    "chunking_profile": "short_business_event_v1",
    "index_profiles": ["vector_default", "fulltext_default", "graph_default"],
    "ignore_patterns": []
  }
]
```

Обязательные поля:

- `code`
- `source_kind`
- `domain`
- `owner`
- `enabled`
- `sync_mode`
- `scope_rule`
- `sensitivity`
- `pii_policy`
- `versioning_mode`
- `extractor_profile`
- `chunking_profile`
- `index_profiles`

### `contracts/ai/memory_profiles.json`

Описывает chunking, embedding, graph extraction и ranking.

Пример:

```json
{
  "chunking_profiles": {
    "short_business_event_v1": {
      "max_tokens": 500,
      "overlap_tokens": 60,
      "preserve_fields": ["number", "status", "department", "updated_at"]
    }
  },
  "embedding_profiles": {
    "local_multilingual_v1": {
      "provider": "local",
      "model": "BAAI/bge-m3",
      "dimensions": 1024,
      "normalization": true
    }
  },
  "ranking_profiles": {
    "default_hybrid_v1": {
      "vector_weight": 0.45,
      "fulltext_weight": 0.30,
      "graph_weight": 0.25,
      "fusion": "rrf",
      "reranker": "local_optional"
    }
  }
}
```

Модели embeddings не фиксировать навсегда. На старте проверить:

- `BAAI/bge-m3` - сильный кандидат для русского/мультиязычного retrieval, поддерживает dense/sparse/multi-vector подходы;
- `intfloat/multilingual-e5-large` - стабильный baseline;
- локальный reranker добавить только после первичной оценки latency/quality.

### `contracts/ai/memory_routing.json`

Описывает, что разрешено отправлять в локальную/облачную LLM.

Пример:

```json
{
  "sensitivity_levels": ["public", "internal", "confidential", "pii_redacted", "pii_original", "secret"],
  "routes": {
    "public": {
      "default_llm": "local",
      "cloud_allowed": true,
      "requires_redaction": false
    },
    "internal": {
      "default_llm": "local",
      "cloud_allowed": true,
      "requires_redaction": true
    },
    "confidential": {
      "default_llm": "local",
      "cloud_allowed": false,
      "requires_redaction": true
    },
    "pii_redacted": {
      "default_llm": "local",
      "cloud_allowed": false,
      "requires_redaction": true
    },
    "pii_original": {
      "default_llm": "local",
      "cloud_allowed": false,
      "requires_redaction": true
    },
    "secret": {
      "default_llm": "deny",
      "cloud_allowed": false,
      "requires_redaction": true
    }
  }
}
```

## Runtime/data model

### Django models

Минимальный набор:

- `MemorySource`: runtime-копия источника из контракта, статус и watermarks.
- `MemorySnapshot`: конкретный raw/safe слепок, hash, source object id, timestamps.
- `MemoryChunk`: chunk metadata, path/hash, active flag, scope tokens, sensitivity.
- `MemoryGraphFact`: derived fact metadata, entity/edge ids, provenance.
- `MemoryIndexJob`: sync/reindex job state, retries, error details.
- `MemoryAccessAudit`: кто, когда и по какому request_id получил memory context.
- `MemoryEvalCase`: тестовые вопросы, ожидаемые источники, forbidden sources/scopes.

Ключевой принцип: Django DB хранит метаданные и authority для access checks. Сами тяжелые индексы лежат в `data/memory/indexes/`.

### Snapshot identity

Каждый snapshot должен иметь:

- `source_code`;
- `source_object_id`;
- `content_hash`;
- `schema_version`;
- `extracted_at`;
- `valid_from`;
- `valid_to`;
- `is_active`;
- `raw_path`;
- `safe_path`;
- `pii_policy_applied`;
- `scope_tokens`;
- `sensitivity`;
- `extractor_version`.

### Scope tokens

Scope tokens не должны быть произвольными строками из LLM.

Их формирует server-side `ScopeTranslator`, например:

- `user:<id>`;
- `role:<role>`;
- `department:<id>`;
- `branch:<id>`;
- `workorder-visible:<user_id>`;
- `org:default`.

Для каждого retrieval запроса:

1. Django строит `allowed_scope_tokens`.
2. Vector/full-text/graph backend получает фильтр.
3. После retrieval Django повторно отбрасывает все chunks, которые не проходят policy.
4. Context assembler получает только разрешенные chunks/facts.

## ELT pipeline

### Stage 1. Discovery

Вход: `memory_sources.json`, integration registry, доменные selectors.

Задачи:

- определить enabled sources;
- применить ignore patterns;
- получить список candidate objects;
- сравнить с предыдущими watermarks/hash;
- создать `MemoryIndexJob`.

Важно: domain mapping остается внутри доменных приложений. Например, извлечение заявок использует `apps.workorders.selectors`, а не общий интеграционный god-object.

### Stage 2. Extract

Вход: доменный объект или внешний API/file snapshot.

Выход: normalized raw document:

```json
{
  "source_code": "workorders_public_timeline",
  "source_object_id": "WO-2026-0001",
  "source_type": "workorder",
  "payload": {},
  "text": "...",
  "metadata": {},
  "extracted_at": "2026-05-19T10:00:00+03:00"
}
```

### Stage 3. Raw Vault write

Запись только в `data/memory/raw_vault/`.

Правила:

- путь детерминированный: `data/memory/raw_vault/<source_code>/<source_object_id>/<content_hash>.json`;
- запись атомарная: temp file + `os.replace`;
- raw snapshot не передается в LLM;
- raw snapshot может быть restricted, если содержит PII;
- safe snapshot создается отдельно.

### Stage 4. De-identification

Для пациентских данных:

- сначала структурная замена известных полей: patient id, phone, email, DOB;
- затем Presidio/custom recognizers по свободному тексту;
- затем DLP scan на секреты;
- затем повторная проверка safe-текста.

Псевдонимизация:

- стабильные токены вида `<PATIENT:7f3a...>`;
- HMAC с секретным salt/key из OpenBao или deployment secret;
- без обратного восстановления в AI runtime.

Если de-identification не прошла:

- snapshot помечается `blocked`;
- индексация не выполняется;
- ошибка попадает в `MemoryIndexJob`;
- оператор видит причину в admin/UI.

### Stage 5. Chunking

Chunking должен быть source-aware:

- регламенты: заголовки, разделы, пункты;
- заявки: события timeline и поля;
- устройства: карточка устройства + история обслуживания;
- интеграционные snapshots: payload-specific extractor.

Каждый chunk получает:

- `chunk_id`;
- `source_code`;
- `source_object_id`;
- `snapshot_hash`;
- `position`;
- `text`;
- `metadata`;
- `scope_tokens`;
- `sensitivity`;
- `valid_from`;
- `valid_to`;
- `is_active`.

### Stage 6. Graph extraction

Графовые факты вводятся сразу.

Минимальные node types:

- `PersonAlias` только для псевдонимов, не ФИО;
- `PatientAlias`;
- `Department`;
- `Role`;
- `MedicalDevice`;
- `WorkOrder`;
- `PolicyDocument`;
- `ClinicalProtocol`;
- `IntegrationSystem`;
- `Concept`;
- `Event`.

Минимальные edge types:

- `ASSIGNED_TO`;
- `LOCATED_IN`;
- `RELATED_TO_DEVICE`;
- `MENTIONS_CONCEPT`;
- `HAS_STATUS`;
- `SUPERSEDES`;
- `VALID_FOR`;
- `DERIVED_FROM`;
- `OPENED_BY`;
- `RESOLVED_BY`.

Каждый edge должен иметь:

- `fact_id`;
- `source_chunk_id`;
- `snapshot_hash`;
- `confidence`;
- `extracted_by`;
- `valid_from`;
- `valid_to`;
- `is_active`;
- `scope_tokens`;
- `sensitivity`.

Graph extraction варианты:

1. Rule-based extractor для структурированных Django models.
2. Local LLM structured extractor для текстовых документов.
3. Graphiti adapter после spike, если он стабильно работает с локальной LLM и Kuzu/FalkorDB.

### Stage 7. Index write

Vector/full-text:

- MVP: LanceDB, потому что embedded и поддерживает metadata filters/hybrid/full-text сценарии.
- Альтернатива: Qdrant, если нужен отдельный vector service, сильная фильтрация payload и лучшее production-разделение.

Graph:

- MVP: Kuzu embedded.
- Альтернатива: Neo4j/FalkorDB, если Graphiti окажется ценным, но Kuzu adapter будет недостаточным.

Важно: index write должен быть idempotent:

- upsert по `chunk_id`/`fact_id`;
- деактивация старых active chunks/facts при новом hash;
- raw history не удаляется;
- index manifest фиксирует backend, schema version, embedding model.

## Retrieval pipeline

### Цель

Получить "микс" знаний из графа, векторов и полнотекста эффективно и безопасно.

### Шаги

1. `memory.search` получает запрос от agent runtime через Django gateway.
2. Request context содержит `actor`, `session_id`, `conversation_id`, `request_id`, `origin_channel`.
3. `SensitivityClassifier` оценивает запрос: содержит ли PII, секреты, медицинскую чувствительность.
4. `ScopeTranslator` строит allowed scopes.
5. `QueryPlanner` выбирает retrieval profile:
   - точный номер/ID/status -> full-text/structured first;
   - "почему/как связано" -> graph first;
   - "найди похожее/объясни по регламенту" -> vector + full-text;
   - mixed/unknown -> parallel hybrid.
6. Выполняются backend searches:
   - vector search;
   - full-text search;
   - graph neighborhood search.
7. `AccessFilter` повторно проверяет результаты через Django metadata.
8. `RankFusion` объединяет результаты.
9. `Reranker` локально уточняет top-N, если включен.
10. `ContextAssembler` собирает компактный контекст с citations.
11. `MemoryAccessAudit` фиксирует выдачу.

### Rank fusion

MVP: Reciprocal Rank Fusion (RRF).

Преимущество RRF:

- простая реализация;
- устойчивость к разным шкалам scoring;
- можно смешивать vector/full-text/graph без преждевременного ML-ranking.

Пример логики:

```text
score(doc) =
  vector_weight * rrf_rank(vector_rank)
  + fulltext_weight * rrf_rank(fulltext_rank)
  + graph_weight * rrf_rank(graph_rank)
  + freshness_boost
  + authority_boost
  - sensitivity_penalty_if_needed
```

Весовые профили должны жить в `memory_profiles.json`, а не в коде.

### Graph contribution

Граф не должен заменять текстовые источники. Он должен:

- находить связанные сущности;
- расширять candidate set;
- объяснять связи;
- повышать score chunks с близкими сущностями;
- помогать ответить на multi-hop вопросы.

Пример:

Запрос: "Какие повторяющиеся проблемы были у аппарата УЗИ в хирургии?"

Pipeline:

1. Full-text находит `УЗИ`, `хирургия`.
2. Graph находит `MedicalDevice -> WorkOrder -> Concept`.
3. Vector search находит похожие описания поломок.
4. Fusion собирает заявки, регламенты и связанные факты.
5. Ответ содержит ссылки на заявки/события, а не только graph summary.

## Local/cloud LLM routing

### Sensitive route gate

Перед каждым LLM call, кроме строго локального, должен работать gate:

```text
input prompt + retrieved context
  -> DLP scan
  -> PII scan
  -> sensitivity labels
  -> policy decision
  -> local/cloud/deny
```

### Запрещено

- Отправлять `pii_original` в облако.
- Отправлять `secret` в любую LLM.
- Полагаться на инструкцию в prompt как на privacy control.
- Давать агенту секреты вместо ссылок/handles.

### Разрешено

- Отправлять `public` в облако.
- Отправлять `internal` в облако только после redaction и если `memory_routing.json` разрешает.
- Отправлять сложную задачу в облако без sensitive context, оставляя локальную LLM для retrieval и data grounding.

### Cloud escalation flow

1. Agent пытается решить локально.
2. Если confidence низкий или задача сложная, runtime просит `route.evaluate`.
3. Gate строит cloud-safe prompt:
   - без PII;
   - без секретов;
   - с агрегированными фактами;
   - с минимальными цитатами, если разрешено.
4. Cloud LLM возвращает reasoning/answer draft.
5. Локальный контур проверяет ответ по источникам и policy.
6. Пользователь видит ответ с отметкой, если использовалась облачная модель.

## AI tool contracts

Добавить в `apps/ai/tool_definitions.py` и `contracts/ai/tools.json`:

### `memory.search`

Mode: read.

Inputs:

- `query`;
- `limit`;
- `source_codes`;
- `domains`;
- `time_mode`;
- `include_graph`;
- `include_citations`.

Outputs:

- `answer_context`;
- `items`;
- `citations`;
- `policy_decision`;
- `retrieval_trace`.

### `memory.get_source`

Mode: read.

Возвращает конкретный безопасный source/chunk по citation id, если пользователь имеет доступ.

### `memory.explain_trace`

Mode: read/admin.

Показывает, почему были выбраны источники. Нужен для отладки и обучения владельца проекта.

### `memory.reindex_source`

Mode: write/admin.

Запускает reindex конкретного source. Требует confirmation.

## UI/Admin

MVP можно начать с Django Admin и management commands.

Минимальные экраны позже:

- список memory sources;
- состояние sync jobs;
- blocked snapshots с причиной;
- retrieval audit;
- eval dashboard;
- ручной запуск reindex;
- просмотр citations без раскрытия PII.

Не нужно сразу делать красивую панель. Сначала важнее наблюдаемость и возможность понять, почему память выдала конкретный контекст.

## План работ

### Этап 0. ADR и технический spike

Цель: снять главные неопределенности до реализации.

Задачи:

1. Создать ADR: `docs/adr/ADR-0003-ai-memory-service.md`.
2. Зафиксировать MVP storage stack:
   - Kuzu для графа;
   - LanceDB как embedded vector/hybrid store или Qdrant как service;
   - SQLite/Django DB для метаданных.
3. Провести spike Graphiti:
   - локальная LLM;
   - Kuzu backend;
   - 20-50 русскоязычных synthetic/business documents;
   - проверка structured output stability;
   - проверка provenance;
   - проверка возможности enforced scopes.
4. Провести spike embeddings:
   - `BAAI/bge-m3`;
   - `intfloat/multilingual-e5-large`;
   - 30-50 тестовых вопросов на русском;
   - метрики: top-k recall, citation accuracy, latency.
5. Принять решение: Graphiti adapter или собственный graph extractor v1.

Acceptance criteria:

- ADR принят.
- Выбран vector backend.
- Выбран graph extraction path.
- Есть mini-eval report в `data/memory/eval/` или `.local/`, если отчет временный.

### Этап 1. Контракты и валидация

Цель: описать память декларативно, как остальные AI-контракты проекта.

Задачи:

1. Добавить:
   - `contracts/ai/memory_sources.json`;
   - `contracts/ai/memory_profiles.json`;
   - `contracts/ai/memory_routing.json`.
2. Добавить schemas в `contracts/schemas/`.
3. Расширить `config/settings.py`:
   - копирование runtime-контрактов в `data/contracts/ai/`;
   - загрузка memory contracts.
4. Расширить `apps/core/json_utils.py` validators.
5. Расширить `validate_architecture_contracts`.
6. Добавить тесты на валидные/невалидные контракты.

Acceptance criteria:

- `python manage.py validate_architecture_contracts` валидирует memory contracts.
- Некорректные source/profile/routing файлы fail-fast при старте.
- Runtime-копии создаются в `data/contracts/ai/`.

### Этап 2. Django app `apps.memory`

Цель: создать системный контур памяти без индексации.

Задачи:

1. Создать Django app `apps.memory`.
2. Добавить модели:
   - `MemorySource`;
   - `MemorySnapshot`;
   - `MemoryChunk`;
   - `MemoryGraphFact`;
   - `MemoryIndexJob`;
   - `MemoryAccessAudit`;
   - `MemoryEvalCase`.
3. Добавить `policies.py`, `selectors.py`, `services.py`.
4. Добавить admin registration.
5. Добавить миграции.
6. Добавить `.desc.json`, обновить `PROJECT_STRUCTURE.yaml`.

Acceptance criteria:

- App подключен в `INSTALLED_APPS`.
- Миграции проходят.
- Admin показывает sources/jobs/snapshots.
- Нет прямой связи с LLM или индексами на этом этапе.

### Этап 3. Raw Vault и safe corpus

Цель: надежно сохранять source snapshots и безопасные версии для индексации.

Задачи:

1. Добавить path settings:
   - `LOCAL_BUSINESS_MEMORY_DIR`;
   - `data/memory/raw_vault`;
   - `data/memory/safe_corpus`;
   - `data/memory/indexes`;
   - `data/memory/manifests`.
2. Реализовать атомарную запись JSON.
3. Реализовать hash calculation.
4. Реализовать snapshot manifest.
5. Добавить command `memory_discover_sources`.
6. Добавить command `memory_sync_source --source <code>`.
7. Добавить unit tests на idempotency и hash updates.

Acceptance criteria:

- Повторный sync без изменений не создает новую active версию.
- Измененный source создает новый snapshot.
- Старый raw snapshot сохраняется.
- Active chunk/fact версии переключаются отдельно от raw history.

### Этап 4. De-identification и DLP

Цель: не допустить PII/секреты в индексируемый корпус и LLM.

Задачи:

1. Добавить `deidentification.py`.
2. Подключить Presidio analyzer/anonymizer.
3. Добавить кастомные recognizer'ы:
   - русские ФИО;
   - телефоны;
   - email;
   - даты рождения;
   - адреса;
   - номера полисов/паспортов, если они встречаются;
   - локальные patient IDs.
4. Добавить deterministic pseudonymization через HMAC.
5. Добавить `CredentialGuard`:
   - API keys;
   - passwords;
   - tokens;
   - private keys;
   - connection strings.
6. Добавить tests:
   - PII redaction;
   - secret blocking;
   - stable pseudonyms;
   - false-negative regression cases.

Acceptance criteria:

- `pii_original` не индексируется.
- Safe corpus не содержит исходные ФИО/телефоны/email.
- Secret-like content блокирует indexing job.
- Все blocked snapshots видны в admin/job logs.

### Этап 5. Chunking и source adapters

Цель: получить качественные chunks из первых источников.

MVP sources:

1. `workorders` без пациентских PII.
2. `inventory` устройства.
3. `role_rules`/`workflow_rules` как контракты.
4. `docs/architecture` и selected регламенты, если есть.

Задачи:

1. Реализовать source adapter interface:
   - `discover()`;
   - `extract(object_ref)`;
   - `build_scope_tokens(payload)`;
   - `build_text(payload)`;
   - `metadata(payload)`.
2. Реализовать adapters для Django models и files.
3. Реализовать chunkers:
   - text document chunker;
   - structured object chunker;
   - event/timeline chunker.
4. Реализовать tests на chunk boundaries и metadata preservation.

Acceptance criteria:

- Каждый chunk имеет source/citation metadata.
- Chunking не смешивает разные access scopes.
- Domain logic остается в соответствующем app/adapter, а не в общем SDK.

### Этап 6. Graph MVP

Цель: графовые узлы и связи создаются сразу и участвуют в retrieval.

Задачи:

1. Добавить `graph_backends.py` interface:
   - `upsert_nodes`;
   - `upsert_edges`;
   - `deactivate_by_snapshot`;
   - `search_entities`;
   - `neighborhood`;
   - `facts_for_chunks`.
2. Реализовать `KuzuGraphBackend`.
3. Создать graph schema v1.
4. Реализовать structured extractors:
   - WorkOrder -> WorkOrder/Department/Device/UserAlias/Event;
   - Inventory -> MedicalDevice/Department;
   - Contract docs -> PolicyDocument/Role/Capability/WorkflowStatus.
5. Реализовать LLM graph extractor только для non-PII safe text.
6. Добавить Graphiti adapter, если spike прошел.
7. Добавить graph tests:
   - node upsert;
   - edge versioning;
   - scope filtering;
   - provenance lookup.

Acceptance criteria:

- Kuzu graph лежит в `data/memory/indexes/kuzu`.
- Каждый graph fact связан с chunk/source.
- Graph retrieval не возвращает facts вне allowed scopes.
- Можно ответить на простые relation-вопросы по заявкам/устройствам.

### Этап 7. Vector/full-text MVP

Цель: включить semantic и lexical retrieval.

Задачи:

1. Добавить `vector_backends.py` interface:
   - `upsert_chunks`;
   - `delete_or_deactivate`;
   - `search_vector`;
   - `search_text`;
   - `search_hybrid`;
2. Реализовать `LanceDBMemoryBackend` или `QdrantMemoryBackend`.
3. Реализовать local embedding provider.
4. Добавить embedding manifest:
   - model;
   - dimensions;
   - normalization;
   - generated_at;
   - source chunk hash.
5. Реализовать metadata filters:
   - active;
   - scope_tokens;
   - sensitivity;
   - source_code;
   - valid time.
6. Добавить tests на filtering.

Acceptance criteria:

- Vector search работает локально.
- Full-text/hybrid search работает локально.
- Фильтр scope применяется в backend и повторно в Django.
- Изменение chunk hash вызывает re-embedding только измененного chunk.

### Этап 8. Retrieval orchestrator

Цель: собрать graph/vector/full-text в единый безопасный `memory.search`.

Задачи:

1. Реализовать:
   - `SensitivityClassifier`;
   - `ScopeTranslator`;
   - `QueryPlanner`;
   - `ParallelRetriever`;
   - `RankFusion`;
   - `ContextAssembler`;
   - `RetrievalTrace`.
2. Добавить route decisions по `memory_routing.json`.
3. Добавить audit log.
4. Добавить `memory.search` tool.
5. Добавить tool tests через Django gateway.
6. Интегрировать `services/agent_runtime/graph.py` без прямого импорта memory internals.

Acceptance criteria:

- Agent может вызвать `memory.search`.
- Ответ содержит citations.
- Запрос пользователя с узкими правами не видит чужие chunks/facts.
- Retrieval trace можно объяснить.

### Этап 9. Планировщик и синхронизация

Цель: автоматизировать обновление памяти.

MVP:

- management commands;
- cron/systemd timer;
- file locks.

Production:

- Celery worker;
- Redis broker;
- django-celery-beat schedule;
- job locks;
- retry/backoff.

Задачи:

1. Реализовать lock на source/job.
2. Реализовать retry policy.
3. Реализовать incremental sync watermarks.
4. Добавить manual reindex tool/admin action.
5. Добавить health command:
   - индексы доступны;
   - contracts валидны;
   - last sync не старше threshold;
   - blocked jobs есть/нет.

Acceptance criteria:

- Одна и та же source не индексируется параллельно.
- Ошибки не ломают весь pipeline.
- Оператор видит состояние sync.

### Этап 10. Evaluation и security gates

Цель: не выпускать memory block без проверяемого качества и безопасности.

Задачи:

1. Создать eval dataset:
   - вопросы по регламентам;
   - вопросы по заявкам;
   - вопросы по устройствам;
   - вопросы с запрещенными scopes;
   - вопросы с PII/secret bait.
2. Метрики:
   - top-k citation recall;
   - answer groundedness;
   - forbidden source leakage;
   - PII leakage;
   - latency p50/p95;
   - reindex duration.
3. Command `memory_eval`.
4. Добавить CI-safe subset без тяжелых моделей.
5. Добавить manual local eval для GPU.

Acceptance criteria:

- Утечки forbidden scope: 0.
- Утечки исходной PII: 0.
- Каждый ответ memory tool содержит citations или явно сообщает, что источников нет.
- Eval report сохраняется в `data/memory/eval/` или `.local/` для временных прогонов.

### Этап 11. UI/Admin hardening

Цель: сделать блок обслуживаемым.

Задачи:

1. Memory hub в Django:
   - sources;
   - jobs;
   - blocked snapshots;
   - eval;
   - retrieval audit.
2. Ручные действия:
   - sync now;
   - reindex source;
   - deactivate source;
   - inspect citation.
3. Permissions:
   - только manager/admin;
   - dangerous actions require confirmation.
4. HTMX partials по текущему стилю проекта.

Acceptance criteria:

- Администратор может понять состояние памяти без shell.
- Нельзя посмотреть raw PII через UI без отдельного разрешения.
- Все actions аудируются.

### Этап 12. Secrets management

Цель: подготовить open-source контур секретов без утечек в LLM.

Решение:

- preferred: OpenBao для service secrets;
- optional: Vaultwarden/Bitwarden-compatible vault для человеческих credentials;
- пока OpenBao не внедрен, использовать private deployment `.env` и не передавать секреты агенту.

Задачи:

1. ADR по secret management.
2. Ввести интерфейс `SecretHandle`:
   - agent видит только handle/metadata;
   - сервис получает секрет server-side;
   - LLM не получает value.
3. Добавить DLP scanner в chat input и memory ingest.
4. Добавить audit для secret handle access.

Acceptance criteria:

- В prompt/tool_trace не попадает secret value.
- Пользователь получает ссылку/handle, а не раскрытый секрет.
- Сервисные интеграции используют server-side secret lookup.

## MVP scope

MVP считается завершенным, если работает следующий сценарий:

1. Администратор включает memory sources для заявок, устройств и контрактов.
2. `memory_sync_source` создает raw/safe snapshots.
3. PII/secret scanner блокирует небезопасные тексты.
4. Kuzu получает graph facts.
5. LanceDB/Qdrant получает chunks.
6. AI agent вызывает `memory.search`.
7. Retrieval смешивает vector/full-text/graph.
8. Пользователь получает ответ с citations.
9. Пользователь без прав не получает чужие источники.
10. `memory_eval` проверяет минимум leakage/grounding cases.

## Что отложить

Не включать в первый релиз:

- полноценный PostgreSQL migration;
- облачную LLM escalation для sensitive context;
- автоматическое re-identification;
- визуализацию графа;
- сложное soft versioning для всех источников;
- отдельный `services/memory_runtime`, если `apps.memory` хватает;
- массовую интеграцию Битрикс24/МИС/телефонии до стабилизации contracts.

## Риски и mitigations

### Риск: graph extraction дает мусор

Mitigation:

- structured extractors для доменных моделей;
- LLM extractor только для safe text;
- confidence threshold;
- graph facts не используются без provenance;
- eval cases для relation questions.

### Риск: PII leakage

Mitigation:

- two-stage de-identification;
- DLP before indexing и before cloud route;
- zero leakage eval;
- blocked snapshots;
- local-only route для `pii_redacted`.

### Риск: RBAC leakage через vector store

Mitigation:

- backend filters;
- повторный Django AccessFilter;
- source/chunk-level scope tokens;
- eval with forbidden scopes;
- fail-closed behavior.

### Риск: слишком тяжелая эксплуатация

Mitigation:

- MVP на embedded Kuzu + LanceDB;
- Qdrant/PostgreSQL только при подтвержденной необходимости;
- management commands до Celery;
- UI после стабилизации pipeline.

### Риск: lock-in в готовый OSS framework

Mitigation:

- свой contract/data model;
- adapters for Graphiti/Cognee/LightRAG;
- export/import manifests;
- tests на поведение, а не на библиотечную реализацию.

### Риск: локальная LLM плохо делает structured extraction

Mitigation:

- rule-based extraction для структурированных sources;
- small ontology;
- strict JSON schema validation;
- retry with repair только локально;
- Graphiti только после spike.

## Проверки перед релизом

Команды проекта:

```bash
make check
make test
make contracts
```

Новые проверки:

```bash
python manage.py memory_sync_source --source workorders_public_timeline --dry-run
python manage.py memory_reindex --source workorders_public_timeline
python manage.py memory_eval --suite smoke
python manage.py validate_architecture_contracts
```

Security checks:

- PII leakage suite;
- secret bait suite;
- forbidden scope suite;
- cloud route denial suite.

Performance checks:

- ingest time per 100 documents;
- p50/p95 retrieval latency;
- graph query latency;
- vector search latency;
- index size growth.

## Источники и актуальные ориентиры

- Cognee docs: https://docs.cognee.ai/setup-configuration
- Graphiti repository/docs: https://github.com/getzep/graphiti
- LightRAG repository: https://github.com/HKUDS/LightRAG
- Mem0 OSS docs: https://docs.mem0.ai/open-source/overview
- LanceDB docs: https://docs.lancedb.com/
- Kuzu docs: https://docs.kuzudb.com/
- Presidio docs: https://microsoft.github.io/presidio/
- LangGraph memory docs: https://docs.langchain.com/oss/python/langgraph/add-memory
- Qdrant filtering docs: https://qdrant.tech/documentation/search/filtering/
- Celery periodic tasks: https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html
- OpenBao: https://openbao.org/
- Bitwarden Secrets Manager: https://bitwarden.com/help/secrets-manager-overview/

## Итоговая рекомендация

Реализовать СоСНА как собственный governance-first memory core:

1. Контракты и policy в Django.
2. Raw/safe corpus в `data/memory`.
3. Kuzu graph с первого MVP.
4. LanceDB embedded на MVP; Qdrant как альтернатива при росте.
5. Presidio + custom recognizers + HMAC pseudonyms.
6. `memory.search` как единственный путь agent runtime к памяти.
7. Graphiti/Cognee/LightRAG использовать только как adapters/spikes, пока они не докажут совместимость с RBAC, PII, provenance и локальной LLM.

