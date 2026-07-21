# Active plan: удаление MemorySnapshot/MemoryChunk из активного пути памяти

Статус: реализовано, ожидает финальной приемки/архивации workflow-блока.

Дата: 2026-05-22.

## Цель

Упростить индексный слой памяти после перехода к файловым знаниям:

- убрать `MemorySnapshot` и `MemoryChunk` из пути сохранения и поиска знаний;
- перестать использовать "снимок" и "фрагмент" как обязательный промежуточный слой;
- заменить их прямой индексной записью, которая ссылается либо на файл знания, либо на объект источника данных;
- сохранить разделение: знания в файлах, данные в источниках, индексы в отдельных хранилищах.

## Контекст

Связанные документы:

- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`;
- `docs/planning/archive/2026/memory-file-backed-knowledge.md`;
- `workflow/archive/2026/memory-file-backed-knowledge/HANDOFF_REPORT.md`.

Исполнительный блок:

- `workflow/archive/2026/memory-snapshot-chunk-removal/`.

## Почему это нужно

`MemorySnapshot` и `MemoryChunk` появились как слой обработки исходных данных:

- `MemorySnapshot` описывает снимок исходного объекта;
- `MemoryChunk` описывает фрагмент обработанного текста для поиска.

После перехода к файловым знаниям этот слой стал лишним для обычной памяти. Для знания уже есть:

- файл знания в `data/knowledge_repo/`;
- `MemoryKnowledgeItem` как запись метаданных;
- поисковые индексы.

Если знание сначала превращать в `MemorySnapshot`, потом в `MemoryChunk`, а потом индексировать, система снова смешивает знания, данные и индексные структуры.

## Целевое состояние

В активном пути используется простая схема:

```text
файл знания
  -> MemoryKnowledgeItem
  -> MemorySearchDocument
  -> полнотекстовый / векторный / графовый индекс
  -> memory.search
```

Для исходных данных:

```text
источник данных
  -> MemorySourceObject
  -> временная обработка
  -> MemorySearchDocument
  -> индекс source_data
```

`MemorySearchDocument` - это техническая запись индекса. Она не является знанием и не хранит полный исходный текст. Она хранит только указатель, права, чувствительность, тип корпуса, статус индексации и безопасные метаданные.

## Предлагаемая модель MemorySearchDocument

Минимальные поля:

- `document_id` - стабильный идентификатор документа в поиске;
- `corpus_type` - `knowledge` или `source_data`;
- `object_kind` - `knowledge_item`, `source_object`, `summary`, `analytics_slice`;
- `knowledge_item` или `knowledge_id` - ссылка на знание, если это корпус знаний;
- `source_object` или `source_object_id` - ссылка на исходный объект, если это корпус данных;
- `source_code`;
- `source_kind`;
- `source_refs`;
- `scope_tokens`;
- `sensitivity`;
- `index_status`;
- `body_hash`;
- `metadata`;
- `created_at`, `updated_at`, `indexed_at`.

Правило: полный текст знания читается из файла знания через reader service. Полный текст исходного документа, письма или API-ответа в этой модели не хранится.

## Объем работ

Входит:

- добавить модель `MemorySearchDocument`;
- перевести индексацию `MemoryKnowledgeItem` на `MemorySearchDocument`;
- изменить полнотекстовый индекс так, чтобы он работал с `document_id`, а не с `chunk_id`;
- изменить `memory.search`, чтобы он возвращал `knowledge_id` и ссылку на источник без чтения `MemoryChunk`;
- перевести fallback по `source_data` на `MemorySourceObject` + `MemorySearchDocument`;
- отключить создание `MemorySnapshot`/`MemoryChunk` в обычном пути `memory.remember`;
- удалить или изолировать админки, сервисы, тесты и команды, которые считают `MemorySnapshot`/`MemoryChunk` обязательной частью памяти;
- подготовить миграцию удаления старых таблиц, если они пустые или перенесены;
- обновить документацию и e2e-проверку.

Не входит:

- детальная стратегия графового поиска;
- новый production backend для векторного поиска;
- внешний API памяти;
- перенос аналитических срезов в DuckDB;
- изменение хранения секретов.

## Важные ограничения

- Знания остаются в файлах, а не в индексной таблице.
- Индексы можно перестроить из файлов знаний и доступных источников.
- Исходные данные не копируются в систему памяти как постоянный слой.
- Временные raw/safe файлы удаляются по регламенту после извлечения знания.
- Проверки прав, `scope_tokens`, чувствительности и надежности источника не ослабляются.
- Секретные значения не индексируются.
- Если в среде уже есть данные в `MemorySnapshot`/`MemoryChunk`, удаление таблиц возможно только после миграции или явного подтверждения, что данных нет.

## Порядок реализации

1. Добавить `MemorySearchDocument` и миграцию.
2. Обобщить поисковый backend с `chunk_id` на `document_id`.
3. Перевести индексацию файловых знаний на `MemorySearchDocument`.
4. Перевести чтение результатов `memory.search` на `MemoryKnowledgeItem` + reader service.
5. Перевести source-data fallback на `MemorySourceObject` + `MemorySearchDocument`.
6. Отвязать графовые факты от `MemorySnapshot`/`MemoryChunk` или временно выключить графовый путь для этого блока.
7. Удалить активные импорты, admin-разделы, тестовые фабрики и команды для `MemorySnapshot`/`MemoryChunk`.
8. Добавить миграцию удаления старых моделей или явный guard, который запрещает удаление при неперенесенных строках.
9. Обновить документацию, контракты и проверки.

## Критерии приемки

- `memory.remember` после обработки очереди создает файл знания, `MemoryKnowledgeItem` и `MemorySearchDocument`, но не создает `MemorySnapshot` и `MemoryChunk`.
- `memory.search` по умолчанию возвращает `result_type=knowledge`, `knowledge_id`, текст знания и `source_refs`.
- Поисковый индекс не требует `chunk_id`.
- Fallback в `source_data` возвращает только безопасные метаданные и ссылку на исходный объект.
- В обычном коде нет импортов `MemorySnapshot` и `MemoryChunk`, кроме миграции или временной команды переноса.
- `MemorySnapshotAdmin` и `MemoryChunkAdmin` удалены или недоступны в MVP.
- Тесты не создают `MemorySnapshot`/`MemoryChunk` для проверки обычной памяти.
- E2E-сценарий проходит путь: `memory.remember -> writer worker -> index worker -> memory.search`.
- Документация больше не описывает `MemorySnapshot`/`MemoryChunk` как обязательный слой памяти.

## Проверки

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests
./.venv/bin/python manage.py memory_eval --dry-run
./.venv/bin/python manage.py memory_file_backed_e2e
npm run test:e2e
git diff --check -- . ':(exclude)BACKLOG.md'
```

## Ожидаемые исполнительные артефакты

После реализации исполнитель должен добавить:

- `workflow/archive/2026/memory-snapshot-chunk-removal/EXECUTOR_REPORT.01-05.md`;
- `workflow/archive/2026/memory-snapshot-chunk-removal/TASK_ACCEPTANCE.01-05.md`;
- `workflow/archive/2026/memory-snapshot-chunk-removal/RETROSPECTIVE.md`.

## Реализованный срез

Выполнено 2026-05-22:

- добавлен `MemorySearchDocument`;
- `memory.remember`, document ingestion и external connector handoff больше не создают новые `MemorySnapshot`/`MemoryChunk`;
- `memory.search` читает знания через файл знания и `MemorySearchDocument`;
- source-data fallback возвращает безопасные метаданные `MemorySourceObject`;
- полнотекстовый backend работает с `document_id`;
- Django Admin показывает `MemorySearchDocument` вместо рабочих разделов snapshots/chunks;
- `MemorySnapshot`, `MemoryChunk` и привязанный к ним `MemoryGraphFact` удалены из модели Django миграцией `0007`;
- графовый поиск временно выключен до отдельной стратегии графового индекса.
