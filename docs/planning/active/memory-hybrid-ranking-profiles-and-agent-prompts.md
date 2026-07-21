# Профили гибридного ранжирования памяти и подсказки ИИ-бота

## Статус

Active planning.

Архитектурное решение: `docs/adr/ADR-0016-memory-hybrid-ranking-profiles.md`.

## Цель

Сделать поиск памяти управляемым и объяснимым:

- нормализовать объединение FTS/BM25 и vector score;
- ввести преднастроенные профили ранжирования;
- научить ИИ-бота выбирать режим поиска по намерению пользователя;
- покрыть выбор режимов e2e-тестами.

## Не цели

- Не реализовывать graph runtime search в этом этапе.
- Не возвращать старую модель `MemoryChunk`.
- Не давать ИИ-боту передавать произвольные веса каналов.
- Не вводить новый внешний API поиска или cloud embeddings.
- Не хранить полный извлеченный текст исходных файлов в `MemorySearchDocument.metadata`.

## Текущая проблема

Сейчас FTS и vector кандидаты объединяются слишком просто:

- FTS5 возвращает BM25-производную оценку;
- LanceDB возвращает vector distance, который преобразуется в score;
- одинаковый документ из разных каналов получает сумму raw score;
- `_rank_score` добавляет authority boost и штрафы.

Такое сложение не является устойчивым, потому что BM25 и vector score живут в разных шкалах.

## Предлагаемая модель

### Параметры

`search_mode` остается главным параметром выбора корпуса и каналов:

```text
knowledge_default
knowledge_precise
knowledge_semantic
knowledge_graph
source_explicit
source_fallback
```

Добавить `ranking_profile` как необязательный параметр. Если он не передан, сервис выбирает профиль по `search_mode`.

```text
knowledge_default   -> balanced
knowledge_precise   -> precise
knowledge_semantic  -> semantic_heavy
source_explicit     -> source_content или source_semantic по намерению пользователя
source_fallback     -> balanced, source fallback использует source_content/source_semantic по намерению пользователя
knowledge_graph     -> graph_future, пока graph channel disabled
```

### Профили

| Профиль | FTS | Vector | Graph | Назначение |
| --- | ---: | ---: | ---: | --- |
| `precise` | 0.90 | 0.10 | 0.00 | Точные номера, коды, названия, даты, термины |
| `balanced` | 0.55 | 0.45 | 0.00 | Обычный поиск сведений по теме |
| `semantic_heavy` | 0.25 | 0.75 | 0.00 | Поиск по смыслу и похожим формулировкам |
| `source_content` | 0.70 | 0.30 | 0.00 | Поиск по содержимому исходных файлов с приоритетом точных совпадений |
| `source_semantic` | 0.30 | 0.70 | 0.00 | Поиск по смыслу в исходных файлах |
| `graph_future` | 0.35 | 0.35 | 0.30 | Заготовка после включения graph runtime search |

`source_data` индексируется в LanceDB сразу в ближайшем этапе, но без нового внешнего API и без cloud embeddings. Доступ остается через существующий `memory.search`.

### Нормализация

MVP-реализация:

1. Получить кандидатов из каждого канала.
2. Для каждого канала назначить rank: `1, 2, 3...`.
3. Посчитать RRF score: `1 / (k + rank)`.
4. Применить веса профиля.
5. Добавить `overlap_boost`, если документ найден несколькими каналами.
6. Добавить authority boost и штрафы доверия.
7. Упаковать результат в context budget.

Raw score backend не использовать как итоговый score. Его нужно сохранять в trace как диагностический сигнал.

### Trace

Каждый ответ `memory.search` должен показывать:

```text
search_mode
ranking_profile
normalization = rrf
weights
candidate_counts
channel_scores.<channel>.raw_score
channel_scores.<channel>.rank
channel_scores.<channel>.rrf_score
overlap_boost_applied
authority_boost_applied
final_score
```

## Подсказки для ИИ-бота

### Системный блок

Добавить или уточнить блок agent runtime:

```text
## Выбор режима поиска памяти

Для поиска используй memory.search.

Если пользователь просит искать точное слово, номер, фразу или термин в
исходных файлах, документах, вложениях, таблицах, xls/xlsx/csv/tsv,
markdown, json/yaml или по содержимому файла,
используй:
  search_mode="source_explicit"
  ranking_profile="source_content"

Если пользователь просит искать по смыслу именно в исходных файлах или
документах, используй:
  search_mode="source_explicit"
  ranking_profile="source_semantic"

Если пользователь просит найти принятое знание по смыслу, похожую инструкцию,
аналогичный случай, близкую формулировку или говорит, что не помнит точные слова,
используй:
  search_mode="knowledge_semantic"
  ranking_profile="semantic_heavy"

Если пользователь ищет точное значение: номер заявки, инвентарный номер,
серийный номер, дату, код, название файла, точный термин или цитату, используй:
  search_mode="knowledge_precise"
  ranking_profile="precise"

Если пользователь просит сначала искать в базе знаний, но разрешает показать
исходные документы при пустом результате, используй:
  search_mode="source_fallback"
  ranking_profile="balanced"
  include_source_data=true

Если пользователь просто просит "найди в памяти" без уточнения, используй:
  search_mode="knowledge_default"
  ranking_profile="balanced"

Не передавай fulltext_weight, vector_weight или graph_weight. Весами управляет
серверный профиль.

Если memory.search вернул kind="source_data", отвечай осторожно: это исходный
документ, а не принятое знание. Не превращай source_data в утвержденный факт без
дополнительного review.
```

### Примеры выбора

| Запрос пользователя | Режим | Профиль |
| --- | --- | --- |
| "Найди документ, где встречается manualftsneedle_xlsx_260526" | `source_explicit` | `source_content` |
| "Поищи по содержимому Excel-файлов про поверку" | `source_explicit` | `source_content` |
| "Найди в файлах по смыслу документы про регулярную проверку кислородного оборудования" | `source_explicit` | `source_semantic` |
| "Найди по смыслу инструкцию про калибровку кислорода" | `knowledge_semantic` | `semantic_heavy` |
| "Где в памяти упоминается заявка WO-12345?" | `knowledge_precise` | `precise` |
| "Найди в базе знаний, а если нет, проверь исходные документы" | `source_fallback` | `balanced` |
| "Что известно про правила обработки заявок?" | `knowledge_default` | `balanced` |

## Source semantic search

Source semantic search входит в ближайший scope. Это означает, что исходные файлы индексируются не только в FTS5, но и в LanceDB через локальную embedding-модель.

Ограничения:

- новый внешний API поиска не включается;
- cloud embeddings не используются;
- `source_data` остается отдельным типом результата и не становится accepted knowledge;
- source vectors используются только в режимах, где `source_data` явно допустим: `source_explicit` и source-часть `source_fallback`;
- `knowledge_semantic` не должен незаметно подмешивать source documents.

### Sensitivity, secrets и PII

Embedding-индексирование разрешено для всех sensitivity уровней.

Исключение: если найден секрет, индексирование конкретного документа блокируется. Reindex должен создать issue `secret_blocked` с severity `blocker`, поставить задачу администратору, удалить старые FTS/vector записи этого документа, если они были, и перейти к следующему документу.

PII и прочие чувствительные признаки не блокируют индексирование и не обезличиваются перед локальными FTS/LanceDB индексами. Reindex должен создать audit/review issue `pii_audit`, сообщить администратору и продолжить индексирование. Issue metadata не должна хранить секреты или необезличенную PII.

### Reindex и удаление

Предлагаемое решение:

- стабильный ключ индекса — `MemorySearchDocument.document_id`;
- LanceDB upsert выполнять как delete+upsert по `document_id`, чтобы не оставлять старые ACL/sensitivity payload;
- FTS upsert выполнять по тому же `document_id`;
- инкрементально переиндексировать только документы с измененным `content_hash`, parser/extraction version, embedding version, ACL/scope fingerprint, sensitivity, trust status, index profile или при `--force`;
- при исчезновении файла переводить `MemorySearchDocument` в `deleted`, удалять FTS row и LanceDB row по `document_id`;
- при обнаружении секрета в ранее проиндексированном документе сначала удалить старые FTS/vector записи, потом создать blocker issue;
- при изменении ACL или sensitivity без изменения текста выполнить metadata reindex через delete+upsert.

### Временная гранулярность

На текущем этапе индексируется документ целиком: один `MemorySearchDocument` дает один FTS-документ и один vector.

Это временное решение. В следующем этапе нужно перейти к `MemorySearchSegment`: крупные разделы документа, листы таблицы или диапазоны строк. Для длинных файлов document-level embedding может снижать качество, поэтому e2e/eval должны фиксировать это ограничение.

## План реализации

1. Расширить tool contract `memory.search`: добавить `ranking_profile`.
2. Добавить серверный каталог профилей в settings или отдельный memory config module.
3. Изменить fusion: не складывать raw score, а хранить per-channel scores и считать RRF.
4. Обновить trace и audit.
5. Обновить agent runtime prompts.
6. Добавить unit-тесты выбора профиля и RRF.
7. Добавить source vector retrieval для `source_explicit` и source-части `source_fallback`.
8. Добавить e2e-набор с контролируемыми документами для `precise`, `balanced`, `semantic_heavy`, `source_content`, `source_semantic`.
9. Зафиксировать document-level source vectors как временное решение до `MemorySearchSegment`.

## Acceptance checks

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python -m unittest services.agent_runtime.tests.test_normalization
python manage.py memory_file_content_search_e2e
```

Дополнительные e2e проверки нового этапа:

- `precise` выше ранжирует точное FTS-совпадение;
- `semantic_heavy` выше ранжирует смысловое совпадение;
- `balanced` дает преимущество документу, найденному несколькими каналами;
- `source_content` ищет по точному содержимому файла и возвращает `source_data` с предупреждением;
- `source_semantic` ищет по смыслу в исходном файле и возвращает `source_data` с предупреждением;
- документ с секретом не индексируется и создает blocker issue;
- документ с PII индексируется и создает audit issue;
- trace содержит профиль, веса, RRF-позиции и итоговый score.
