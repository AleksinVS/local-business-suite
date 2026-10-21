# LLM-Wiki — развитие существующей системы знаний LBS

Статус: proposed target, **без переписывания с нуля**.

## 1. Точная исходная точка

В актуальной реализации `apps.memory` (сверить `main` SHA перед PR) уже есть:

- `data/knowledge_repo/**/*.md` как авторитетный формат знаний, YAML frontmatter, Git-история и `memory_reconcile`; переключаемый режим `LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE` — фактический режим на конкретном хосте проверить отдельно;
- `memory.remember`, синхронная запись в файл и commit, inline index, retry queue для переиндексации;
- `MemoryKnowledgeItem`, `MemorySearchDocument`, `MemoryAccessAudit`, FTS, экспериментальный vector backend;
- lifecycle `pending/current`, интерфейсы review, защита от молчаливого снижения classification;
- `source_data` отдельно от accepted `knowledge`, source adapters, envelope и source provenance;
- `MemoryKnowledgeEdge` из `relations:` и утверждённого словаря; **graph runtime search не внедрён**;
- Filehub — отдельное замороженное приложение, не считать частью обязательной Wiki;
- заглушки data store, отсутствующий production OCR/PDF/DOCX ingestion и отсутствие полноценного внешнего Wiki API.

Источники: `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`, `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md`, `docs/architecture/hybrid-knowledge-architecture-v0.5.md`, `apps/memory/*`.

**Вывод:** нет смысла заменять канон, ACL, review и audit готовым generic RAG. Следует сделать `KnowledgeProvider` в LBS Factory поверх существующего кода, одновременно убрать Django-специфичную связанность и ненужные экспериментальные ветки.

## 2. Модель LLM-Wiki

```
Read-only external IS / interviews / docs / chat excerpts
                  |
          Source adapters + ACL
                  |
      Source Staging (original/ref/hash)
                  |
     Synthesizer/Extraction Agent
                  |
      Wiki Proposal (pending + citations)
                  |
           Human review policy
                  |
    Accepted Wiki pages (Markdown/Git)
                  |
  Index projection (PostgreSQL FTS, optional vector)
                  |
     Knowledge API -> agents/chat/support
```

Wiki — **знания об организации и её процессах**, не замена ERP/CRM и не универсальное хранилище сырой истории чатов. Источник нормализованных бизнес-данных остаётся в своём домене, retrieval в Wiki может возвращать ссылку на него и извлекать актуальное значение через provider.

## 3. Сущности и стадии

### SourceRecord

Файл, интервью, документ, исходное событие, заметка, объект Bitrix/1C, ссылка и снимок. Обязательны origin/system, stable source id, timestamp/as_of, classification, owner, authenticity/provenance, ACL, retention и content hash. Непроверенный source всё равно может быть полезным для поиска в **source corpus**, но не является утверждённым знанием.

### WikiConcept

Человекочитаемая Markdown-страница с устойчивой идентичностью, категорией, авторством, владельцем, ссылками на источники, классом конфиденциальности, статусом review и revision. Канон живет в Git, PostgreSQL хранит метаданные и индексы. На MVP не вводить отдельную глобальную графовую БД или claims/beliefs платформу.

### WikiProposal

Предложение созданное агентом на основании источников. Не становится `current` из-за высокой model confidence. Для безопасных низкорисковых категорий может быть policy-approved автоматизация, но внутренние политики, персональные данные, финансы, безопасность и процессные регламенты требуют явного уполномоченного reviewer.

### WikiCitation

Ссылка `source_ref`, `source_version/content_hash`, location (страница/раздел/строка, если доступно), дата, classification. Пользователь должен иметь доступ к самой цитате и подтверждающему материалу; нельзя раскрывать скрытые пути или содержание источника только потому, что на него сослался агент.

### KnowledgeAccessContext

Идентичность организации, user/agent/service, проверенные права, разрешённые scope/compartments, запрет egress для чувствительных сведений. Сохраняется запрет выдачи до проверки прав — и при чтении кандидатов, и при возврате текста/цитаты.

## 4. Wiki API (минимальная стабильная поверхность)

```
knowledge.search(query, corpus, limit, actor_ctx) -> citations + permitted snippets
knowledge.get(concept_ref, actor_ctx) -> concept + revision + provenance
knowledge.propose(concept, source_refs, actor_ctx) -> proposal_ref
knowledge.review(proposal_ref, decision, reviewer_ctx) -> revision/status
knowledge.history(concept_ref, actor_ctx) -> revisions
knowledge.sources(concept_ref, actor_ctx) -> validated source refs
knowledge.reconcile(dry_run|apply, privileged_ctx) -> report
```

Все операции доступны как локальный интерфейс; HTTP/MCP адаптеры добавляются как потребители. Отдельный network Wiki Service на первом этапе не нужен, если основное приложение продолжает обслуживать Wiki.

`knowledge.remember`: совместимый адаптер старого AI tool, но для нового discovery flow запись по умолчанию означает **proposal или source staging**, не безусловный коммит в принятую организационную Wiki. Это намеренное уточнение прежнего поведения; миграция должна сохранять старые сценарии по версии API/feature flag.

## 5. Политика знаний из обследования

Пример:

1. Пользователь рассказывает: «Ремонтные заявки иногда приходят в WhatsApp».
2. Сохраняется raw/excerpt SourceRecord с доступом участников интервью (при наличии согласия/правила сохранения).
3. Agent создаёт Proposal: «Используется WhatsApp как неформальный канал подачи заявок» с источником, временем, статусом `unverified`.
4. Интервью/дополнительный источник подтверждает обстоятельства или опровергает гипотезу.
5. Владелец процесса утверждает окончательную формулировку в Wiki; все старые версии и изменения доступны по audit.
6. AI support отвечает на основании `current` концептов, а при явном запросе может отдельно показать неподтверждённые сведения, помеченные статусом и с учетом ACL.

### Инварианты

- Не индексировать как принятую истину необработанные чаты и результаты агентов.
- Снижение sensitivity/расширение ACL — только через отдельный review с журналом, не автоматический merge.
- Synthesized page наследует наиболее закрытую классификацию используемых источников; деклассификация — отдельное действие уполномоченного лица.
- Источник может устареть: должны существовать `last_verified_at`, `review_due_at` *как опциональные поля* и состояние needs-review по правилам владельца. Не строить сложный time-series engine для Wiki.
- Запрос пользователя не даёт прав на чужие источники даже если агент имеет административный runtime token.
- Если нужно удалить реальные ПДн, обычного `git rm` недостаточно: есть история/реплики/индексы/backups. Нужна явная процедура удаления и отдельное решение о допустимости помещения такой информации в Git.

## 6. Физическое хранение и изоляция

- **Обычные approved pages**: Markdown/Git под контролируемым write service; не хранить секреты в commit history.
- **Чувствительные корпоративные знания**: ограниченные группы, по необходимости отдельные репозитории/хранилища на реальные границы `need-to-know`, не по каждому отделу без оснований.
- **Raw documents**: вне wiki git, ссылки на существующие оригиналы или защищенное файловое хранилище; доступ по источнику.
- **Metadata/audit**: существующий PostgreSQL. SQLite возможно в компактном/локальном режиме при выбранном deployment profile.
- **FTS**: PostgreSQL FTS базовый on-prem backend; vector retrieval только если сравнительный evaluation показывает выигрыш.
- **Object storage**: optional, если большие файлы/распределённая установка.

### Многопроцессность

Нынешний filesystem lock + Git writer работает для одного writer host/общего локального FS при выполнении исходных предположений. При нескольких самостоятельных узлах нет оснований считать такой lock распределённой гарантией. Сначала один writer (в одном процессе или отдельном небольшом writer service), затем при необходимости очередь writer jobs. Не создавайте распределённый Git cluster заранее.

## 7. Упрощение существующей кодовой базы

| Сейчас | Цель | Действие |
|---|---|---|
| `apps.memory` привязана к Django и AI tooling | `KnowledgeProvider` интерфейс | Обернуть фасадом без немедленного extraction в отдельный repo |
| `memory.remember` inline Git + inline search indexing | Каноническая запись отдельно от производной индексации | Сначала замерить, затем по необходимости async index; пока вернуть `index_pending` и использовать direct get |
| `MemoryExternalConnectorJob` смешивает background/reindex/source jobs | Выделить общую семантику `Job`, сохранить конкретную реализацию | Не переносить в универсальный bus до необходимости |
| `SourceObjectEnvelope` общий, external connectors в memory | Коннектор отдаёт SourceRecord/Envelope в Registry | Reuse adapter, владельцем предметного source остаётся интеграционный компонент |
| Graph extraction/ranking-профили в ADR | Не обязательно реализовывать | Оставить только полезные det. relations, runtime graph search позже |
| `apps.filehub` сложный и замороженный | Optional File Organization | Не размораживать без customer pilot |
| Множество будущих DataStore концептов | За рамками Wiki MVP | Не смешивать Wiki и аналитическую БД |
| Нет Wiki API для внешних агентов | `KnowledgeProvider` API с ACL | Сделать локально, затем MCP read API после principal binding |

**Не сносить** audit, privacy gates, review, source provenance, Git history и данные существующих инсталляций ради сокращения количества файлов. Удалять только доказанное дублирование/неиспользуемые ветки с миграциями и тестами.

## 8. Что стоит получить от готового ПО

Использовать готовые библиотеки для file parsers/OCR, embeddings/FTS/vector и рендеринга Markdown. Предусмотреть `SearchBackend`, `DocumentParser` и `EmbeddingProvider` только при реальных альтернативных реализациях; на старте не вводить «универсальный универсал» десятка адаптеров.

Нельзя сразу выбирать внешнюю RAG-платформу вместо LLM-Wiki: она должна пройти тест по предметным правам, provenance, версиям, review, доступу к исходникам и offline/on-prem. Готовый продукт может использоваться как engine поиска или внешнее UI, если соответствует контрактам.

## 9. Контракт минимальной Wiki-страницы

```yaml
---
knowledge_id: proc-maintenance-intake
kind: Process
lifecycle: pending
owner: technical_department
sensitivity: internal
scope_tokens: [project:alpha]
sources:
  - ref: source:interview-2026-10-12#q7
    version: sha256:...
relations: []
---
```

Буквальные поля — **предлагаемая совместимая цель**, а не утверждение, что все они уже поддерживаются текущим frontmatter валидатором. Существующий формат нужно сохранить и дополнять явной версионируемой миграцией, а не переписывать файлы массово.

## 10. Тесты приёмки

- Исходный документ не появляется как принятый Wiki-факт без review.
- Wiki research-agent не видит документ чужого отдела и не возвращает его содержание через citation/fallback.
- Manual downgrade classification вызывает pending, а не автоматическое открытие.
- Выданная цитата воспроизводится по ревизии и source reference при наличии доступа.
- Повторный reconcile без изменений не создаёт новых ревизий/работ.
- Перестроение индекса не меняет канон.
- Отказ индексатора не уничтожает принятую страницу; статус индекса виден пользователю.
- Secret leakage test: секреты не попадают в Markdown, Git history, индексы, логи, prompt внешней модели.
- Удаление/архивация источника корректно обрабатывает ссылки; в sensitive-case запускается предусмотренный runbook.
- Прежние `memory.search` и `memory.remember` остаются совместимыми в утверждённом режиме миграции.

## 11. Нужные ADR

- Новая граница `KnowledgeProvider`, судьба `apps.memory` как Django app.
- Политика source→proposal→accepted, включая чат, Telegram и Битрикс24.
- Политика хранения ПДн/retention/Git erase.
- Точка выполнения ACL и federated identity/agent context.
- Явное решение по индексации (inline vs background) после измерений.

## 12. Связь с LBS Access (v3.3)

- `KnowledgeProvider` не обязан реализовывать роли, но **обязан применять** проверенные grants, item/source ACL, классификацию и trusted-context до передачи body, citations, title, path и relations в ответ/LLM.
- Авторство, право `knowledge.propose`, право `knowledge.review` и право `knowledge.publish` различаются; принятые знания не появляются автоматически из Telegram/группового чата.
- Проверка отправки результата в групповую комнату не ограничивается источником запроса: должны учитываться подтверждённые получатели и room policy. При неустановленной аудитории защищённые материалы не использовать.
- `apps.memory.policies` остаётся владельцем предметных правил Wiki, но больше не должно быть единственным источником общей идентичности/ролей; адаптер получает проверенный `TrustedActorContext` из `LBS Access` или внешнего `AuthorizationProvider`.
- Ревокация права и изменение классификации требуют инвалидации/проверки доступа к индексу/артефактам. Старые ссылки и результаты поиска не являются постоянным допуском.

Полная модель и тесты: `07_ACCESS_ARCHITECTURE.md`, `08_ACCESS_MIGRATION_AND_TESTS.md`.
