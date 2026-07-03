# ADR-0030: LLM-maintained knowledge wiki layer for memory

## Статус

Proposed

## Дата

2026-06-17

## Контекст

Проект уже имеет governance-first систему памяти, которая строже обычного RAG:

- исходные данные не становятся постоянным источником истины внутри памяти;
- принятые знания хранятся в `data/knowledge_repo/` как Markdown-файлы с YAML front matter и Git-историей;
- метаданные, права, статусы и индексы хранятся отдельно;
- агент читает память только через `memory.search`, с `citations`, проверкой scope/sensitivity/trust и `MemoryAccessAudit`;
- `source_data` остается отдельным корпусом исходных объектов и не считается принятым знанием;
- организационные знания и спорные материалы проходят candidate/review flow;
- graph runtime search, claim/belief lifecycle, production OCR/parser cascade и фрагментный поиск по большим документам остаются будущими этапами.

Внешняя идея, рассмотренная для развития памяти: LLM-maintained wiki, описанная в gist `llm-wiki` Андрея Карпати. Суть подхода:

- raw sources остаются неизменяемым источником;
- LLM ведет производный wiki-слой: summary, entity pages, topic pages, links, contradictions, synthesis;
- правила ведения wiki описаны в schema/instructions;
- ingest, query и lint работают не только с raw documents, но и с накопленным знанием;
- полезные ответы могут сохраняться как новые страницы, чтобы анализ не терялся в истории чата.

Эта идея частично уже совпадает с принятыми решениями проекта:

- ADR-0003 фиксирует governance-first memory service;
- ADR-0004 описывает ingestion документов и moderated graph schema bootstrapping;
- ADR-0009 вводит trusted sources, future claim/belief слой и легкий retrieval hot path;
- ADR-0011 фиксирует файловые знания в `data/knowledge_repo/`;
- ADR-0013 запрещает считать базу или индекс источником полного текста знания;
- ADR-0015 и ADR-0016 развивают full-text/vector search и гибридное ранжирование.

Но текущий runtime еще не является полноценной wiki. Он ближе к реестру атомарных знаний:

- `MemoryKnowledgeItem` хранит метаданные, а текст лежит в файле знания;
- `_summary.md` пересобирается как линейный список активных знаний;
- `knowledge_reflection_worker` сейчас пересобирает summaries и создает кандидатов в организационные знания;
- нет отдельного типа страницы синтеза: topic/entity/procedure/decision/comparison page;
- нет устойчивых wiki-ссылок между знаниями, страницами, графовыми сущностями и source refs;
- нет регулярного wiki-lint для противоречий, сиротских страниц, устаревших утверждений, scope mixing и отсутствующих citations;
- хорошие ответы AI-чата не имеют управляемого пути превращения в проверяемые wiki-страницы.

## Текущая система памяти

### 1. Контракты и правила

Default-контракты лежат в `contracts/ai/`, runtime-копии - в `data/contracts/ai/`.

Ключевые контракты:

- `memory_sources.json` - каталог источников памяти;
- `memory_profiles.json` - профили extraction/indexing/retrieval;
- `memory_ingestion_profiles.json` - профили local/UNC ingestion, parser/OCR cascade, limits и raw policies;
- `memory_routing.json` - маршрутизация по sensitivity;
- `memory_trust_policy.json` - доверенность источников;
- `memory_claims_policy.json` - будущая политика claim/belief lifecycle;
- `memory_retrieval_budget.json` - лимиты retrieval hot path;
- `memory_graph_schema.json` - утвержденная схема графа памяти.

### 2. Источники данных и `source_data`

Исходные данные остаются в своих системах:

- чаты;
- файлы local/UNC источников;
- заявки и лист ожидания через `SourceAdapter`;
- внешние API через reference connector;
- будущие email/DMS/API источники;
- аналитические факты.

В памяти они представлены как source objects/search documents, но не как принятые знания. Корпус `source_data` можно искать явно или как fallback, но результат должен показываться как исходный объект, а не как утвержденный факт.

### 3. Privacy, security и trust gate

Перед попаданием в контур памяти данные проходят проверки:

- secret scanning;
- secret handles вместо записи секретных значений;
- sensitivity routing;
- PII/privacy pipeline по профилю источника;
- trusted-only gate для прямого agent context;
- review queue для skipped, partial, unsupported, suspicious и рискованных объектов.

Trust не заменяет права доступа. Даже trusted source не может обойти scope/sensitivity checks.

### 4. Принятые знания

Принятое знание - это очищенный короткий текст с source refs, scope, sensitivity, статусом и правами.

Рабочий путь:

```text
memory.remember
  -> MemoryWriteRequest
  -> MemoryIndexJob
  -> writer worker
  -> data/knowledge_repo/**/*.md
  -> MemoryKnowledgeItem
  -> MemorySearchDocument
  -> full-text/vector index
  -> memory.search
```

Текст знания хранится только в файле знания. `MemoryKnowledgeItem` хранит metadata, hashes, status, path и provenance. `MemorySearchDocument` является поисковой карточкой и не является источником полного текста.

### 5. Поиск и выдача агенту

`memory.search` является основным read path:

- фильтрует по scope/sensitivity/trust;
- ищет по корпусам `knowledge` и, при явном разрешении, `source_data`;
- использует full-text backend и optional vector backend;
- возвращает compact context и citations;
- пишет `MemoryAccessAudit`.

Обычный ответ агента должен опираться на `knowledge`. `source_data` можно использовать как ссылку на исходный объект или материал для review/candidate flow.

### 6. Review, audit и фоновые workers

Система имеет:

- `MemoryIngestionIssue`;
- `MemoryReviewAction`;
- review UI для ingestion/index issues;
- `MemoryAccessAudit`;
- `knowledge_writer_worker`;
- `knowledge_index_worker`;
- `knowledge_reflection_worker`;
- eval/smoke commands.

Полноценная ночная reflection пока не реализована: текущий worker выполняет только базовую пересборку summaries и создание кандидатов.

## Решение

Ввести управляемый **knowledge wiki layer** как производный слой над текущими файловыми знаниями, без замены существующего `memory.search`, `MemoryKnowledgeItem`, `source_data`, review/audit и контрактов.

### 1. Назначение wiki-слоя

Wiki-слой нужен для накопительного синтеза:

- тематические страницы;
- страницы процедур;
- страницы сущностей;
- страницы решений;
- сравнения;
- обзорные summaries;
- страницы противоречий и открытых вопросов;
- индекс и журнал изменений.

Wiki-страница не является исходным документом. Она является производным знанием, построенным из принятых знаний и разрешенных source refs.

### 2. Размещение

Предварительная структура runtime Git-репозитория:

```text
data/knowledge_repo/
  org/
    _summary.md
    wiki/
      index.md
      log.md
      topics/
      procedures/
      entities/
      decisions/
      comparisons/
      lint/
  users/
    <user_id>/
      _summary.md
      wiki/
        index.md
        log.md
        topics/
        preferences/
        decisions/
```

Этот каталог остается runtime state и не коммитится в основной репозиторий проекта.

### 3. Метаданные wiki-страницы

Каждая wiki-страница должна иметь YAML front matter:

```yaml
wiki_page_id: wiki_org_topic_...
page_type: topic
title: ...
scope: organization
owner_user_id: null
sensitivity: internal
scope_tokens:
  - org:default
review_status: candidate
source_refs: []
knowledge_refs: []
source_data_refs: []
related_pages: []
supports: []
contradicts: []
supersedes: []
generated_by: knowledge_reflection_worker
generated_at: 2026-06-17T00:00:00+03:00
last_validated_at: null
```

Текст страницы должен быть кратким, проверяемым и ссылаться на исходные знания. Запрещено копировать большие raw documents, секреты, необезличенную PII или материалы вне доступного scope.

### 4. Metadata model

При реализации добавить отдельную metadata-модель, например `MemoryWikiPage`, вместо перегрузки `MemoryKnowledgeItem`.

Причины:

- `MemoryKnowledgeItem` остается атомарным знанием;
- wiki page является синтезом из нескольких знаний и источников;
- для страницы нужны отдельные поля: `page_type`, `review_status`, `related_pages`, `knowledge_refs`, `last_validated_at`;
- поиск сможет индексировать wiki page как отдельный `MemorySearchDocument` с `object_kind="wiki_page"`;
- текст страницы по-прежнему хранится только в файле.

### 5. Writer/reader rules

Запись wiki-страниц выполняется только через memory service:

```text
wiki page proposal
  -> policy/scope/trust check
  -> candidate or reviewed status
  -> temporary file
  -> atomic replace
  -> Git commit
  -> metadata update
  -> index job
  -> review/audit event
```

Прямой доступ агента к файлам wiki запрещен. Чтение идет через reader/search service с теми же scope/sensitivity/trust rules, что и для знаний.

### 6. Ingest/query/lint operations

#### Ingest

Новый source object или chat memory не должен автоматически превращаться в reviewed wiki page.

Порядок:

```text
source_data
  -> privacy/security gate
  -> source_data index
  -> candidate/accepted MemoryKnowledgeItem
  -> optional wiki page proposal
  -> review
  -> indexed wiki page
```

#### Query

Если пользователь задает вопрос:

1. `memory.search` ищет в reviewed wiki pages и atomic knowledge.
2. Если wiki page найдена, агент получает ее как synthesis context вместе с citations.
3. Atomic knowledge остается evidence layer.
4. `source_data` подключается только явно или как fallback.
5. Полезный новый ответ может стать wiki page proposal, но не автоматически reviewed page.

#### Lint

Добавить отдельный wiki-lint контур:

- страницы без входящих/исходящих ссылок;
- страницы без citations;
- ссылки на удаленные или superseded знания;
- scope mixing;
- sensitivity mismatch;
- устаревшие утверждения;
- противоречия;
- дубли тем;
- missing topic/entity/procedure pages;
- source_data, ошибочно представленное как accepted knowledge.

Lint по умолчанию работает в `--dry-run` и создает review issues/proposals, а не переписывает знания автоматически.

### 7. Index and log

Wiki-слой должен иметь два служебных файла:

- `index.md` - содержательный каталог страниц с краткими описаниями и ссылками;
- `log.md` - хронологический журнал ingest/query/lint/wiki updates с parseable headings.

Эти файлы являются производными. Их можно пересобрать из metadata и Git history.

## Что изменится в проекте

### Изменится

- Появится новый слой `wiki pages` между atomic knowledge и ответом агента.
- `knowledge_reflection_worker` станет не только пересборщиком `_summary.md`, но и генератором wiki proposals/lint reports.
- `memory.search` сможет возвращать не только atomic `knowledge`, но и `wiki_page` как reviewed synthesis context.
- В review UI появятся wiki page proposals и lint findings.
- В `data/knowledge_repo/` появятся `wiki/index.md`, `wiki/log.md` и тематические страницы.
- В eval появятся сценарии: citations completeness, stale page detection, scope isolation, contradiction reporting.
- В документации памяти появится объяснение различий:
  - `source_data` - исходный объект;
  - `MemoryKnowledgeItem` - атомарное принятое знание;
  - `MemoryWikiPage` - производная reviewed/candidate страница синтеза.

### Не изменится

- Сырье остается в исходных системах.
- `data/knowledge_repo/` остается runtime Git-репозиторием, не частью основного repo.
- `MemoryKnowledgeItem` остается главным атомарным знанием MVP.
- `MemorySearchDocument` остается технической поисковой карточкой.
- `memory.search` остается единственным read path агента.
- Scope/sensitivity/trust/audit остаются обязательными.
- Организационные знания и организационные wiki pages не публикуются без review.
- Graph runtime search и full claim/belief lifecycle не включаются автоматически этим решением.

## Альтернативы

### Оставить только текущий RAG/knowledge search

Проще, но система продолжит каждый раз собирать синтез из отдельных атомарных знаний и source refs. Хорошие ответы будут теряться в истории чата или оставаться неуправляемыми.

### Вести свободную Obsidian-like wiki вручную или агентом

Отклоняется для корпоративного runtime. Свободная wiki плохо сочетается с RBAC, sensitivity, audit, source trust и review. Она может быть полезна как личный инструмент владельца, но не как production memory layer.

### Хранить wiki-страницы в `docs/`

Отклоняется. `docs/` - проектная документация и source of truth для разработки. Wiki-страницы памяти являются runtime knowledge и могут содержать персональные/корпоративные сведения. Их место - `data/knowledge_repo/`.

### Использовать внешний markdown search tool как основной слой

Отклоняется как основной путь. В проекте уже есть policy-aware `memory.search`, audit, FTS/vector backends и контракты. Внешний markdown search может быть вспомогательным tool/spike, но не должен обходить права и audit.

### Сначала реализовать полноценный claim/belief layer

Отложено. Claim/belief важен для строгого управления противоречиями, но wiki-слой можно внедрять раньше как reviewed synthesis над текущими `MemoryKnowledgeItem`, не требуя полного NLI/claim runtime.

## Последствия

### Положительные

- Знания начинают накапливаться как связанный слой, а не только как список атомарных записей.
- Ответы агента становятся более стабильными: сначала synthesis page, затем evidence.
- Становится проще видеть пробелы: нет страницы, нет citations, есть противоречия, устарел source.
- Git history остается для всех принятых изменений.
- Wiki-lint дает регулярную проверку качества памяти.
- Подход хорошо совместим с будущими graph runtime search и claim/belief layer.

### Отрицательные

- Появляется новый тип runtime-артефакта и metadata model.
- Нужны новые review workflows, UI и eval cases.
- LLM-generated synthesis может ошибаться, поэтому review и citations обязательны.
- Нужно строго предотвращать смешивание scope/sensitivity на одной странице.
- Слишком ранняя автоматизация может создать много слабых страниц и review noise.
- Индексация и retrieval должны уметь ранжировать wiki pages и atomic knowledge без скрытого вытеснения evidence.

## Реализационные правила

1. Начинать с `Proposed` wiki pages и `--dry-run` lint, без автоматической публикации reviewed organization pages.
2. Не писать wiki pages напрямую из agent runtime без server-side policy check.
3. Не хранить raw source text в wiki pages.
4. Каждая содержательная страница должна иметь `knowledge_refs` или `source_refs`.
5. Если страница смешивает разные sensitivity/scope, она должна блокироваться или дробиться.
6. `source_data` не может быть представлен как accepted fact без candidate/review.
7. `index.md` и `log.md` должны быть пересобираемыми производными файлами.
8. Любая реализация требует unit tests, memory e2e и обновления операторской документации.

## Требуемые действия перед реализацией

- Создать проектный план `docs/planning/active/...`.
- Решить, нужен ли отдельный контракт `memory_wiki_policy.json` или расширение существующих memory contracts.
- Спроектировать `MemoryWikiPage` metadata model и миграцию.
- Описать формат wiki page front matter и JSON Schema.
- Добавить dry-run команду wiki lint.
- Добавить review flow для wiki proposals.
- Обновить `MEMORY_MVP_CURRENT_STATE.md`, `MEMORY_USER_GUIDE.md` и deployment/operations docs после первого implementation slice.
- Добавить e2e checks для `memory.search` с wiki pages, citations и scope isolation.

## Связанные материалы

- External concept: `https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f`.
- ADR-0003: AI Memory Service Architecture.
- ADR-0004: Memory Ingestion Connector and Graph Schema Bootstrapping.
- ADR-0009: Trusted memory sources, claim/belief layer and lightweight retrieval.
- ADR-0011: Файловые знания, раздельные базы и единый поиск.
- ADR-0013: Текст знания только в файле знания.
- ADR-0015: FTS и векторный поиск по содержимому файлов.
- ADR-0016: Профили гибридного ранжирования памяти.
