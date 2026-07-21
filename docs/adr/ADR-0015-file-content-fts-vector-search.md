# ADR-0015: FTS и векторный поиск по содержимому файлов

## Статус

Accepted

## Дата

2026-05-26

## Контекст

После упорядочивания MVP-памяти фактический runtime использует файловые знания в `data/knowledge_repo/`, `MemorySearchDocument` как техническую карточку индекса и SQLite token fallback вместо настоящего FTS5. Векторный поиск, graph runtime search и reranking пока отключены.

Следующий этап должен дать поиск по содержимому файлов, а не только по именам и metadata. Этап затрагивает:

- извлечение текста из текстовых и табличных файлов с блокировкой секретов; PII-политика уточнена в ADR-0016;
- настоящий SQLite FTS5;
- последующий векторный поиск;
- поддержку `.xlsx` и обязательную поддержку legacy `.xls`;
- правила reindex;
- границу `knowledge` и `source_data`;
- управление режимами поиска со стороны AI-агента.

## Решение

Реализовать поиск по содержимому файлов в два среза.

### Срез 1. FTS и извлечение текста

Первый срез включает:

- сервис извлечения текста из файлов внутри `apps.memory`;
- поддержку `.txt`, `.md`, `.log`, `.json`, `.yaml`, `.yml`, `.csv`, `.tsv`;
- поддержку `.xlsx` и `.xls`;
- документный индекс: один `MemorySearchDocument` индексируется как один поисковый документ;
- настоящий SQLite FTS5;
- опциональный prefix fallback для FTS-запросов;
- token fallback, если FTS5 недоступен;
- расширение `memory_reindex`;
- e2e-сценарий поиска по содержимому файла.

В MVP поиск по фрагментам не реализуется. Индексируется текст документа целиком после secret gate; PII-политика уточнена в ADR-0016. Результат поиска возвращает документ, а не конкретный раздел, лист или диапазон строк.

Полный извлеченный текст не хранится в `MemorySearchDocument.metadata`.

### Срез 2. Векторный поиск

Второй срез включает:

- LanceDB как первый vector backend;
- локальный embedding provider;
- отдельные профили для тестовой легкой модели и целевой production-модели;
- запрет cloud embeddings для содержимого файлов в этом контуре;
- гибридное объединение FTS и vector candidates;
- reranking как planned/optional слой, выключенный по умолчанию.

Qdrant принимается как допустимая production-альтернатива на будущее, но не как первый backend MVP.

### Табличные файлы `.xls` и `.xlsx`

Для MVP использовать `python-calamine` как единый read-only parser для `.xls` и `.xlsx`.

Причины:

- обязательная поддержка `.xls` не покрывается `openpyxl`;
- `python-calamine` опирается на Calamine, который читает legacy `.xls` и современные Excel-форматы;
- один parser снижает сложность по сравнению с парой `openpyxl` + `xlrd`;
- read-only extraction лучше соответствует задаче индексирования текста.

Правила MVP:

- читать только значения ячеек;
- не исполнять макросы;
- не пересчитывать формулы;
- для формул использовать сохраненное значение, если parser его возвращает;
- защищенные, битые и зашифрованные файлы пропускать с issue visibility;
- ограничивать max sheets, rows, cells и extracted text bytes;
- `.xlsm`, `.xlsb`, `.ods` не включать в гарантированный MVP scope, даже если backend может их читать.

Если pilot corpus покажет проблемы с legacy `.xls`, допустим fallback `xlrd` только для `.xls` отдельным решением. LibreOffice/headless conversion в MVP не включается.

### Гранулярность индекса

MVP индексирует документ целиком.

Фрагментный поиск по крупным разделам откладывается на следующий этап. Для следующего решения подготовлены варианты:

1. `MemorySearchSegment` в Django.
2. Manifest только внутри FTS/vector backend.
3. Sidecar manifest в `data/indexes/manifests/` плюс backend payload.

Рекомендуемое направление для следующего этапа - `MemorySearchSegment` без хранения полного текста. Такая таблица будет хранить только `segment_id`, `document_id`, порядок, путь раздела, лист/диапазон строк, hash и версии parser/segmenter/model.

### FTS и prefix search

SQLite FTS5 включается как основной полнотекстовый backend.

Prefix search разрешен как fallback:

- включается, если обычный FTS дал мало результатов или 0 результатов;
- применяется только к словам нормальной длины;
- отражается в trace как отдельный режим;
- не заменяет будущую русскую морфологию.

Русская морфология не входит в MVP. Связка FTS5 + prefix fallback + будущий vector search считается достаточной для первого baseline.

### AI-агент и режимы поиска

AI-агент выбирает режим поиска, а не сырые числовые веса каналов.

Допустимая модель:

```text
knowledge_precise   -> профиль с большим весом FTS
knowledge_semantic  -> профиль с большим весом vector
knowledge_graph     -> accepted compatibility mode, graph remains not_ready
source_explicit     -> explicit source_data search
source_fallback     -> knowledge first, then source_data fallback
```

Сервис применяет заранее заданный профиль ранжирования и пишет его в trace.

Не разрешать агенту напрямую передавать `fulltext_weight`, `vector_weight` или `graph_weight` в tool payload.

### `source_data`

`source_data` сохраняет текущую семантику:

- обычный ответ агента опирается на `knowledge`;
- файлы из `source_data` доступны через явный режим или fallback;
- результат `source_data` всегда помечается как исходный объект, а не принятое знание;
- полный текст исходного файла не становится accepted knowledge.

### Reranking

Reranking фиксируется как planned/optional слой второго среза.

Ограничения:

- только локальный reranker;
- выключен по умолчанию;
- ограничен `top_k`;
- не обязателен для горячего пути;
- отражается в trace;
- не используется для данных, где нельзя безопасно получить текст для rerank.

## Рассмотренные альтернативы

### Qdrant первым backend

Плюсы:

- сильные payload filters;
- удобен как отдельный production vector service;
- лучше подходит для роста нагрузки и независимого обслуживания.

Минусы:

- добавляет новый runtime-сервис;
- усложняет Windows/local deployment;
- требует отдельного lifecycle, healthcheck, backup и мониторинга.

Решение: не использовать первым backend MVP. Оставить как production evolution path.

### SQLite vector table с cosine scan

Плюсы:

- минимум зависимостей;
- простая отладка.

Минусы:

- слабая production-перспектива;
- придется быстро переписывать backend;
- плохо совпадает с решением сразу выбрать Qdrant/LanceDB-класс.

Решение: отклонено.

### `openpyxl` + `xlrd`

Плюсы:

- понятные специализированные библиотеки;
- `openpyxl` хорошо покрывает `.xlsx`;
- `xlrd` может закрыть `.xls`.

Минусы:

- два parser path;
- разные типы ошибок и поведения;
- больше кода нормализации.

Решение: оставить fallback-вариантом, если `python-calamine` не пройдет pilot corpus.

### LibreOffice/headless conversion

Плюсы:

- может открыть больше Office-файлов.

Минусы:

- внешний бинарник;
- сложнее sandbox, timeout и deployment;
- выше риск эксплуатационных сбоев.

Решение: не включать в MVP.

### Фрагментный поиск сразу

Плюсы:

- выше точность поиска;
- лучше для длинных документов;
- проще показать конкретный раздел или диапазон строк.

Минусы:

- новая модель сегментов;
- больше индексов и правил cleanup;
- выше риск расползания первого FTS-среза.

Решение: отложить. В MVP индексировать документ целиком, варианты сегментации подготовить для следующего решения.

### Сырые веса каналов в tool payload

Плюсы:

- гибко для экспериментов.

Минусы:

- сложнее тестировать;
- выше риск нестабильного поведения агента;
- графовый канал сейчас не готов;
- оператору сложнее объяснить результаты.

Решение: отклонено. Агент выбирает `search_mode`, сервис выбирает профиль.

## Последствия

Положительные:

- поиск по содержимому файлов становится реализуемым без преждевременного усложнения;
- `.xls` поддерживается в ближайшем MVP;
- векторный backend сразу имеет путь к production-уровню через LanceDB;
- будущий фрагментный поиск не блокирует FTS-срез;
- `source_data` не смешивается с принятым знанием.

Ограничения:

- документный индекс хуже для длинных файлов, чем фрагментный;
- FTS без русской морфологии может не находить разные формы одного слова;
- prefix fallback может давать шум;
- `.xls` качество зависит от конкретных legacy-файлов;
- forced reindex после изменения parser/segmenter/model должен заново читать исходные файлы.

## Проверки реализации

Минимум для среза 1:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reindex --corpus all --backend fulltext --dry-run
python manage.py memory_file_content_search_e2e
```

Минимум для среза 2:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_reindex --corpus all --backend vector --dry-run
python manage.py memory_eval --dry-run
```

## Связанные документы

- `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`
- `docs/planning/active/memory-file-content-fts-and-vector-search.md`
- `docs/planning/archive/2026/memory-architecture-simplification-and-search.md`
- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`
- `docs/adr/ADR-0013-file-only-knowledge-body.md`
