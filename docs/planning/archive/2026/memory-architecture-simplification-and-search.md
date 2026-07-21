# Archived plan: упорядочивание архитектуры памяти

Статус: архитектурная очистка реализована и архивирована 2026-05-26. FTS и векторный поиск выделены в отдельную будущую проработку и не входили в реализацию этого среза.

Дата: 2026-05-26.

## Цель

Реализовать предложения архитектурного ревью по упрощению и очистке текущей MVP-границы памяти. FTS и векторный поиск по содержимому файлов оставлены отдельным будущим этапом.

Итоговое состояние должно быть понятным:

- что уже является рабочей MVP-памятью;
- какие контуры заморожены до отдельных решений;
- какие active/workflow-планы завершены и архивированы;
- как `knowledge` отличается от `source_data`;
- какие каналы поиска реально работают;
- что остается на следующие этапы: FTS/vector, OCR, граф, claim/belief, MLflow, production parser cascade.

## Контекст

Связанные решения и планы:

- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`;
- `docs/adr/ADR-0009-trusted-memory-sources-claims-and-lightweight-retrieval.md`;
- `docs/adr/ADR-0010-memory-mvp-simplification.md`;
- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/adr/ADR-0013-file-only-knowledge-body.md`;
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`;
- `.local/memory-architecture-review-2026-05-26.md`.

Ревью зафиксировало две группы работ:

1. Упорядочить архитектурную и planning-границу памяти:
   - убрать ложное обещание работающего графового поиска;
   - привести backlog и active plans к текущему состоянию;
   - зафиксировать текущую MVP-схему одним коротким документом;
   - решить судьбу `data/memory/chat_knowledge/`;
   - остановить развитие external connector до выбора pilot source;
   - не развивать claim/belief, MLflow и граф до отдельных решений.
2. Реализовать поиск по содержимому:
   - настоящий FTS;
   - реальный векторный поиск;
   - извлечение безопасного текста из текстовых и табличных файлов;
   - поиск по содержимому `source_data`, а не только по metadata.

## Границы

Входит в первую очередь:

- документ "текущее состояние MVP памяти";
- очистка backlog и active plans по памяти;
- архивирование завершенных workflow-блоков;
- снятие неготовых runtime-обещаний про граф;
- фиксация `source_data` как корпуса ссылок и безопасного поиска по исходным объектам, а не корпуса принятых знаний;
- решение по `data/memory/chat_knowledge/` как legacy event log или удаляемому слою;
- заморозка external connector до выбора pilot source;
- явное откладывание claim/belief, MLflow quality tracing и graph runtime search.

Затем входит технический срез поиска:

- индексирование содержимого `data/knowledge_repo/**/*.md` для корпуса `knowledge`;
- извлечение безопасного текста из текстовых и табличных файлов для корпуса `source_data`;
- поддержка минимум `.txt`, `.md`, `.log`, `.csv`, `.tsv`, `.json`, `.yaml`, `.yml`;
- решение по `.xlsx`: легкий parser через отдельный ADR/решение по зависимости или явное откладывание до parser-backend этапа;
- content-aware `MemorySearchDocument` для `source_data` без хранения полного текста в metadata;
- настоящий SQLite FTS5, если доступен;
- fallback на текущий token index, если FTS5 недоступен;
- векторный backend и embedding provider для локального семантического поиска;
- reindex-команда для пересборки FTS и vector индексов;
- unit-тесты и e2e-сценарий через management command.

Не входит:

- OCR изображений и сканов;
- распознавание встроенных изображений в PDF/DOCX/XLSX;
- production parser cascade для PDF/DOC/DOCX/XLS;
- graph facts и графовый поиск;
- claim/belief lifecycle;
- production UI для review;
- внешний API памяти;
- подключение реального внешнего источника данных;
- MLflow quality tracing.

## Архитектурные правила

### Не расширять неготовые контуры

До отдельного решения и готового сценария не развивать:

- графовый runtime search;
- claim/belief layer;
- MLflow/Ragas/DeepEval контур;
- external connector за пределы reference implementation;
- OCR/image ingestion.

Эти контуры могут оставаться в документации как future-stage, но не должны выглядеть как готовое поведение MVP.

### Источник истины

Для `knowledge` источником текста остается файл знания в `data/knowledge_repo/`.

Индекс не должен быть источником текста для выдачи. Он может хранить производные структуры:

- FTS postings;
- токены fallback-индекса;
- embeddings;
- `document_id`;
- технические признаки ранжирования;
- безопасные metadata для ранней фильтрации.

### Source data

Для `source_data` исходный файл остается в своем источнике. Система памяти хранит:

- `MemorySourceObject`;
- `MemorySearchDocument`;
- хэши;
- scope/sensitivity metadata;
- производные индексы.

Полный извлеченный текст source-файла не должен записываться в `MemorySearchDocument.metadata`. Если нужен временный safe text для индексирования, он должен жить только в процессе или во временной зоне `data/processing/safe_work/` с последующей очисткой.

### Безопасность

Перед индексированием содержимого source-файла обязательно:

- secret scan;
- deidentification/pseudonymization для PII по текущему MVP-контуру;
- scope resolution;
- sensitivity route check;
- issue creation при блокировке, частичном индексировании или ошибке извлечения.

## Порядок реализации

### Этап 1. Зафиксировать текущую MVP-границу памяти

1. Создать короткий документ текущего состояния, например `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`.
2. Описать в нем фактический рабочий путь:

```text
memory.remember
  -> MemoryWriteRequest
  -> knowledge_writer_worker
  -> data/knowledge_repo/**/*.md
  -> MemoryKnowledgeItem
  -> MemorySearchDocument
  -> memory.search
```

3. Явно описать, что сейчас не является готовым runtime:
   - graph search;
   - claim/belief;
   - OCR/image ingestion;
   - MLflow quality tracing;
   - production external connectors.
4. Привести ссылки из README/architecture/user guide к этому документу, если они сейчас создают неоднозначность.

Критерий готовности: у проекта есть один короткий источник правды о текущей MVP-памяти.

### Этап 2. Очистить planning и workflow

1. Пройти active memory-планы и разделить их на:
   - действительно active;
   - реализовано и ожидает приемки;
   - устарело из-за более нового ADR/плана.
2. Архивировать завершенные workflow-блоки:
   - `memory-mvp-simplification`;
   - `memory-mvp-remediation`;
   - `memory-snapshot-chunk-removal`;
   - `memory-file-only-knowledge-body`;
   - другие блоки только после проверки acceptance-файлов.
3. Обновить `docs/planning/backlog.md`:
   - убрать завершенные задачи из Active;
   - оставить только реальные ближайшие работы;
   - перенести future-stage направления в Next/Later.
4. Обновить `.desc.json` и `PROJECT_STRUCTURE.yaml`.

Критерий готовности: backlog не содержит завершенные memory-задачи как active work.

### Этап 3. Убрать ложные runtime-обещания

1. В контрактах и документации явно пометить search channels:
   - `fulltext`: enabled/degraded;
   - `vector`: planned до реализации этапа 8;
   - `graph`: disabled/not_ready.
2. Убрать `graph_default` из runtime-профилей, где он создает ожидание рабочего поиска.
3. В `memory.search` trace явно показывать, что графовый канал отключен, а не просто вернул 0.
4. Обновить пользовательские и deployment-документы: текущий поиск не должен обещать готовый graph search.

Критерий готовности: оператор и пользователь видят фактические каналы поиска, а не целевую архитектуру будущих этапов.

### Этап 4. Уточнить `source_data`

1. Зафиксировать правило: `source_data` - это исходные объекты и ссылки на них, а не принятые знания.
2. В выдаче `memory.search` для `source_data` всегда показывать предупреждение "исходный объект, не принятое знание".
3. Обновить документацию: обычный ответ агента должен опираться на `knowledge`, а `source_data` используется явно или как fallback.
4. Проверить, что source result не возвращает полный исходный текст как accepted knowledge.

Критерий готовности: граница `knowledge` vs `source_data` понятна в коде, документации и результатах поиска.

### Этап 5. Решить судьбу `data/memory/chat_knowledge/`

1. Сравнить ADR-0005 и ADR-0011/0013.
2. Принять одно из решений:
   - оставить `data/memory/chat_knowledge/` как legacy event log без статуса source of truth;
   - остановить запись в этот слой и перенести нужный audit в `data/knowledge_repo/`/metadata;
   - оставить временную совместимость с датой удаления.
3. Если меняется архитектурная роль слоя, обновить ADR или добавить короткое ADR-дополнение.
4. Обновить код и документацию так, чтобы canonical knowledge был только в `data/knowledge_repo/`.

Критерий готовности: в проекте нет двух конкурирующих файловых источников истины для chat-derived memory.

### Этап 6. Заморозить external connector до pilot source

1. Зафиксировать current status: reference implementation есть, production connector не стартует без pilot source.
2. Перенести дальнейшее развитие external connector из Active в Next/Later, если pilot source не выбран.
3. Оставить только maintenance-проверки reference implementation и security gaps, если они нужны для безопасности.
4. Не добавлять новые connector stages, adapters или queue backends до заполнения questionnaires и выбора владельца данных.

Критерий готовности: external connector не конкурирует с поисковым срезом за active scope.

### Этап 7. Отложить claim/belief, MLflow и граф в отдельные будущие решения

1. Зафиксировать, что `MemoryClaim`/`MemoryBelief` не входят в MVP active path.
2. MLflow-план оставить черновиком или Later до появления стабильного retrieval baseline.
3. Графовый runtime search вынести в отдельный будущий план после FTS/vector.
4. В backlog оставить только ссылки на будущие workstreams без активного scope.

Критерий готовности: ближайший этап не расползается за пределы поиска и текущей MVP-границы.

## Технический этап: FTS и векторный поиск

Этот этап начинается после выполнения этапов 1-7 или после явной фиксации, какие пункты из 1-7 сознательно отложены.

### Этап 8. Уточнить контракты и режимы готовности поиска

1. Добавить в contracts явный статус каналов поиска:
   - `fulltext`: enabled;
   - `vector`: enabled/disabled/degraded;
   - `graph`: disabled/not_ready.
2. Уточнить `memory_profiles.json` и `memory_retrieval_budget.json`, чтобы горячий путь не обещал граф.
3. Зафиксировать fallback-поведение, если FTS5 или embedding provider недоступны.
4. Проверить, нужен ли отдельный ADR для выбора embedding-модели, vector storage и `.xlsx` parser dependency.

Критерий готовности: контракты валидны, документация не обещает неработающий графовый поиск.

### Этап 9. Извлечение текста из поддержанных файлов

1. Ввести сервис `source_text_extraction` внутри `apps.memory`.
2. Реализовать извлечение:
   - plain text: `.txt`, `.md`, `.log`;
   - structured text: `.json`, `.yaml`, `.yml`;
   - tabular text: `.csv`, `.tsv`.
3. Для `.csv`/`.tsv` нормализовать строки и колонки в безопасный search text.
4. Для больших файлов сохранить частичное индексирование с issue visibility.
5. Для `.xlsx` принять одно из решений:
   - добавить легкую зависимость и extractor после ADR;
   - временно создавать `UNSUPPORTED_FORMAT`/`requires_parser_backend`.

Критерий готовности: файл, где искомое слово есть только внутри содержимого, находится через `memory.search`.

### Этап 10. Настоящий FTS-индекс

1. Переделать `SQLiteFTSMemoryBackend`, чтобы он использовал SQLite FTS5, если модуль доступен.
2. Использовать contentless/external-content подход, чтобы индекс не становился источником выдаваемого текста знания.
3. Сохранить token fallback для сред без FTS5.
4. Разделить `corpus_type=knowledge` и `corpus_type=source_data` в ранжировании.
5. Добавить миграцию/cleanup старой структуры индекса через пересборку, а не ручное изменение runtime-БД.

Критерий готовности: FTS5 используется в обычной среде, а fallback явно отражается в trace.

### Этап 11. Векторный поиск

1. Ввести интерфейс embedding provider:
   - `embed_text(text) -> vector`;
   - `embed_query(query) -> vector`;
   - version/model metadata.
2. Выбрать MVP-хранилище векторов:
   - локальная SQLite vector table с cosine scan для малого объема;
   - LanceDB/Qdrant только после отдельного решения, если нужен production backend.
3. Ввести локальный embedding provider:
   - предпочтительно локальная multilingual-модель;
   - cloud embeddings запрещены для чувствительных данных без отдельного route gate.
4. Индексировать:
   - файлы знаний;
   - безопасный извлеченный текст source-файлов;
   - только разрешенные sensitivity levels.
5. В `memory.search` объединять FTS и vector candidates детерминированно, без обязательного LLM rerank.

Критерий готовности: смысловой запрос находит документ, даже если точной формы слова в запросе нет, и trace показывает `vector_used=true`.

### Этап 12. Reindex и эксплуатационные команды

1. Расширить `memory_reindex`:
   - `--corpus knowledge|source_data|all`;
   - `--backend fulltext|vector|all`;
   - `--source-code`;
   - `--dry-run`;
   - `--force`.
2. Добавить команду проверки индексов:
   - количество документов в metadata;
   - количество FTS-записей;
   - количество vector-записей;
   - расхождения по `document_id`;
   - failed/degraded причины.
3. Добавить e2e smoke-команду для поиска по содержимому файлов.

Критерий готовности: оператор может пересобрать индексы и увидеть расхождения без ручного доступа к SQLite-файлам.

### Этап 13. Документация и приемка поискового среза

1. Обновить `docs/guides/MEMORY_USER_GUIDE.md`.
2. Обновить `docs/deployment/MEMORY_DEPLOYMENT.md`.
3. Обновить `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md` статусом текущего среза.
4. Обновить backlog: FTS/vector больше не planning-only, а реализованный baseline.

Критерий готовности: документация описывает реальное поведение поиска, а не будущую целевую архитектуру.

## Целевая схема поиска после FTS/vector

```text
memory.search
  -> resolve route and scope
  -> FTS candidates
  -> vector candidates
  -> merge/rank
  -> load MemorySearchDocument
  -> check permissions, sensitivity, trust
  -> for knowledge: read text from knowledge file
  -> for source_data: return source link and safe citation, not accepted knowledge text
```

Графовый канал в этом срезе должен быть явно отключен или помечен как `not_ready`, чтобы не создавать ложное ожидание качества.

## Критерии приемки всего плана

- Есть короткий документ текущего состояния MVP памяти.
- Backlog не держит завершенные memory-задачи в Active.
- Завершенные workflow-блоки по памяти архивированы или явно оставлены active с причиной.
- Graph runtime search помечен как disabled/not_ready.
- External connector не развивается без выбранного pilot source.
- `data/memory/chat_knowledge/` не конкурирует с `data/knowledge_repo/` как source of truth.
- Claim/belief, MLflow и OCR находятся вне ближайшего active scope.
- Поиск по тексту файла знания возвращает `knowledge` результат.
- Поиск по слову, которое есть только внутри `.txt` или `.md` source-файла, возвращает `source_data` результат.
- Поиск по значению из `.csv` или `.tsv` возвращает соответствующий `source_data` результат.
- Source result явно помечен как исходный объект, а не принятое знание.
- `MemorySearchDocument.metadata` не содержит полный извлеченный текст.
- Секреты блокируются или заменяются до индексирования.
- Original PII не попадает в выдачу и индексы в запрещенных режимах.
- FTS5 используется, если доступен; fallback отражается в trace.
- Векторный backend участвует в поиске и отражается в trace.
- Reindex можно выполнить по корпусу и backend.
- Есть unit-тесты и e2e-тест через management command.

## Проверки

Минимум:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_eval --dry-run
```

Новые проверки для поискового среза:

```bash
python manage.py memory_reindex --corpus all --backend all --dry-run
python manage.py memory_file_content_search_e2e
```

После изменения структуры документации:

```bash
make gen-struct
```

Если появится новая зависимость для `.xlsx` или embeddings:

```bash
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests
```

## Риски

- Архивирование active-планов может скрыть незавершенный acceptance gap, если не проверить workflow reports.
- Решение по `chat_knowledge` может потребовать ADR-дополнение.
- Реальные embeddings могут добавить тяжелую зависимость и заметное время индексации.
- `.xlsx` без новой библиотеки или LibreOffice/Docling не будет качественно поддержан.
- FTS5 может быть недоступен в части SQLite-сборок; fallback должен быть рабочим.
- Source-файлы могут содержать PII/секреты, поэтому content indexing нельзя делать до DLP/deidentification.
- Если source_data начнет возвращать слишком много текста, оно начнет конкурировать с принятыми знаниями и нарушит границу `knowledge` vs `source_data`.

## Что отложено после этого плана

- OCR изображений и сканов.
- PDF/DOC/DOCX production parser.
- XLS legacy parser.
- Графовый поиск.
- Claim/belief слой.
- MLflow quality tracing.
- Production queue backend для внешних коннекторов.
