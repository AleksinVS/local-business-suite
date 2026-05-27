# FTS и векторный поиск по содержимому файлов

Статус: implemented, archived.

Дата: 2026-05-26.

Итог реализации 2026-05-26:

- добавлен `apps.memory.source_text_extraction` для текстовых, CSV/TSV и `.xls/.xlsx` файлов;
- SQLite FTS5 включен как основной полнотекстовый backend с token fallback и prefix fallback;
- добавлен LanceDB vector backend и локальные embedding providers;
- `memory_reindex` расширен параметрами `--corpus`, `--backend`, `--source-code`, `--dry-run`, `--force`;
- добавлена команда `memory_file_content_search_e2e`;
- MVP по-прежнему возвращает документ целиком, а не фрагмент/раздел.

## Цель

Реализовать поиск по содержимому файлов в памяти без смешивания исходных файлов (`source_data`) с принятыми знаниями (`knowledge`).

Работа делится на два среза:

1. Извлечение текста, `.xls/.xlsx`, SQLite FTS5, prefix fallback, reindex и e2e.
2. LanceDB, локальные embeddings, hybrid search и optional reranking.

Архитектурное решение: `docs/adr/ADR-0015-file-content-fts-vector-search.md`.

## Принятые решения

- Vector backend для MVP: LanceDB.
- Qdrant остается production-альтернативой на будущее.
- Embeddings только локальные.
- Для тестов допустима легкая модель, для production - целевая multilingual-модель.
- Cloud embeddings для файлового контента запрещены.
- `.xls` обязателен в ближайшем MVP.
- `.xls` и `.xlsx` читать через `python-calamine`.
- MVP индексирует документ целиком.
- Поиск по крупным разделам и сегментам откладывается на следующий этап.
- Reranking фиксируется как planned/optional и реализуется не раньше vector-среза.
- FTS MVP: SQLite FTS5 + опциональный prefix fallback.
- AI-агент выбирает `search_mode`, а не числовые веса FTS/vector/graph.
- Graph runtime search остается `disabled/not_ready`.

## Non-goals

Не входит в ближайший FTS-срез:

- фрагментный поиск по разделам;
- OCR изображений и сканов;
- PDF/DOC/DOCX production parser;
- `.xlsm/.xlsb/.ods` как гарантированный scope;
- graph runtime search;
- cloud embeddings;
- обязательный reranking;
- UI для review индексирования.

## Срез 1. FTS и извлечение текста

### 1. Сервис извлечения текста

Добавить сервис `apps.memory.source_text_extraction`.

Форматы MVP:

- `.txt`;
- `.md`;
- `.log`;
- `.json`;
- `.yaml`;
- `.yml`;
- `.csv`;
- `.tsv`;
- `.xlsx`;
- `.xls`.

Для табличных файлов:

- нормализовать строки в безопасный search text;
- сохранять имена листов в безопасной metadata;
- ограничивать количество листов, строк, ячеек и байтов текста;
- для больших файлов создавать issue и partial indexing;
- не выполнять макросы;
- не пересчитывать формулы;
- для формул брать сохраненное значение, если parser его возвращает.

Полный извлеченный текст нельзя писать в `MemorySearchDocument.metadata`.

### 2. Документный индекс

В MVP один `MemorySearchDocument` соответствует одному индексируемому поисковому документу.

Текст для FTS строится как безопасная производная:

```text
source file / knowledge file
  -> parser
  -> secret scan
  -> deidentification
  -> safe search text
  -> FTS index
```

Результат `memory.search` возвращает документ. Для `source_data` он содержит warning, что это исходный объект, а не принятое знание.

### 3. SQLite FTS5

Переделать текущий `SQLiteFTSMemoryBackend`:

- включить FTS5, если он доступен;
- использовать contentless/external-content подход, чтобы FTS не становился источником выдаваемого текста;
- сохранить token fallback;
- добавить prefix fallback при малом числе результатов;
- писать в trace, какой режим использован.

### 4. Reindex

Расширить `memory_reindex`:

```bash
python manage.py memory_reindex --corpus knowledge|source_data|all --backend fulltext|vector|all --source-code <code> --dry-run --force
```

Обычный reindex должен пропускать неизмененные файлы по `content_hash` и версиям производной логики.

Forced reindex нужен, если изменились:

- parser version;
- deidentification rules;
- FTS schema;
- prefix/tokenization rules;
- embedding model;
- vector backend;
- будущий segmenter.

Если исходный файл недоступен, reindex не должен восстанавливать текст из metadata. Документ помечается degraded/failed с issue visibility.

### 5. E2E

Добавить e2e-команду:

```bash
python manage.py memory_file_content_search_e2e
```

Сценарии:

- слово есть только внутри `.txt`, файл находится;
- слово есть только внутри `.md`, файл находится;
- значение есть только в `.csv/.tsv`, файл находится;
- значение есть только в `.xlsx`, файл находится;
- значение есть только в `.xls`, файл находится;
- source result возвращается с warning;
- полный текст не появляется в `MemorySearchDocument.metadata`;
- trace показывает `fulltext`, `prefix_search_used`, fallback и ошибки индексирования.

## Срез 2. LanceDB и embeddings

### 1. LanceDB backend

Добавить vector backend на LanceDB.

Целевой путь хранения:

```text
data/indexes/vector/lancedb/
```

Payload point/table row должен содержать:

- `document_id`;
- `corpus_type`;
- `source_code`;
- `source_kind`;
- `source_object_id`;
- `scope_tokens`;
- `sensitivity`;
- `content_hash`;
- `embedding_model`;
- `embedding_version`;
- `indexed_at`.

### 2. Локальные embeddings

Добавить embedding provider interface:

```text
embed_text(text) -> vector
embed_query(query) -> vector
model metadata
```

Профили:

- тестовый легкий provider для CI/local smoke;
- production multilingual provider.

Cloud embeddings в этом контуре запрещены.

### 3. Hybrid search

`memory.search` должен объединять FTS и vector candidates детерминированно:

```text
FTS candidates
  + vector candidates
  -> rank fusion
  -> policy/trust/sensitivity filters
  -> packed results
```

AI-агент выбирает только `search_mode`. Сервис применяет заранее заданный ranking profile.

### 4. Reranking

Reranking остается planned/optional:

- локальный;
- выключен по умолчанию;
- ограничен `top_k`;
- отражается в trace;
- не обязателен для горячего пути.

## Следующее архитектурное решение: поиск по фрагментам

MVP сознательно не реализует поиск по крупным разделам. Для следующего этапа подготовлены варианты.

### Вариант A. `MemorySearchSegment` в Django

Схема:

```text
MemorySearchDocument
  -> MemorySearchSegment
  -> FTS row by segment_id
  -> vector point by segment_id
```

`MemorySearchSegment` не хранит полный текст. Поля:

- `segment_id`;
- `document_id`;
- `ordinal`;
- `section_path`;
- `sheet_name`;
- `row_range`;
- `text_hash`;
- `parser_version`;
- `segmenter_version`;
- `embedding_model_version`;
- `index_status`.

Плюсы:

- проще сверять FTS/vector с Django metadata;
- проще удалять устаревшие segment records;
- trace может показать конкретный раздел;
- admin/debug проще;
- backend не становится единственным manifest.

Минусы:

- нужна миграция;
- больше строк в БД;
- больше правил синхронизации.

### Вариант B. Manifest только в FTS/vector payload

Плюсы:

- меньше Django-моделей;
- быстрее первый prototype.

Минусы:

- труднее проверять расхождения;
- сложнее cleanup устаревших фрагментов;
- сложнее audit/debug;
- FTS/vector backend начинает хранить слишком много управляющего состояния.

### Вариант C. Sidecar manifest в `data/indexes/manifests/`

Схема:

```text
data/indexes/manifests/<document_id>.json
FTS/vector payload contains segment_id
```

Плюсы:

- не требует миграции;
- manifest живет рядом с индексами;
- проще пересобрать вместе с индексом.

Минусы:

- сложнее transactional consistency;
- надо писать cleanup и atomic replace;
- хуже видимость в admin;
- возможны расхождения с Django metadata.

### Предварительная рекомендация

Для следующего этапа предпочтителен вариант A: `MemorySearchSegment` в Django без хранения полного текста.

## Критерии приемки среза 1

- `.txt/.md/.log/.json/.yaml/.yml/.csv/.tsv/.xlsx/.xls` проходят extraction или дают понятную issue.
- Поиск находит файл по слову или значению, которое есть только внутри содержимого.
- FTS5 используется в обычной среде.
- Token fallback работает, если FTS5 недоступен.
- Prefix fallback включается только как fallback и отражается в trace.
- `MemorySearchDocument.metadata` не содержит полный извлеченный текст.
- `source_data` возвращается только явно или как fallback и с warning.
- `memory_reindex` поддерживает corpus/backend/source/dry-run/force.
- Есть unit-тесты и e2e-команда.

## Критерии приемки среза 2

- LanceDB индекс создается в `data/indexes/vector/lancedb/`.
- Embeddings создаются локально.
- Тестовый и production embedding profiles разделены.
- Hybrid search объединяет FTS и vector candidates.
- `knowledge_semantic` использует vector profile.
- Trace показывает vector backend, model version и fallback.
- Reranking остается выключенным по умолчанию.

## Проверки

Для среза 1:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_file_content_search_e2e
```

Для среза 2:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py memory_eval --dry-run
```

После изменения структуры:

```bash
make gen-struct
```
