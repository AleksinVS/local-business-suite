# Block brief: удаление MemorySnapshot/MemoryChunk из активного пути памяти

## Цель

Упростить систему памяти после перехода к файловым знаниям: заменить обязательный слой `MemorySnapshot`/`MemoryChunk` прямой индексной записью `MemorySearchDocument`.

## Архитектурные источники

- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`
- `docs/planning/active/memory-file-backed-knowledge.md`
- `docs/planning/active/memory-snapshot-chunk-removal.md`
- `workflow/active/memory-file-backed-knowledge/HANDOFF_REPORT.md`

## Проблема

Сейчас файловое знание уже является главным источником истины, но поиск по знанию проходит через совместимый слой:

```text
MemoryKnowledgeItem
  -> MemorySnapshot
  -> MemoryChunk
  -> search backend
```

Это усложняет модель:

- знание выглядит как обработанный источник данных;
- индексная запись называется "памятью";
- `source_data` и `knowledge` снова смешиваются;
- будущая миграция становится дороже.

## Целевой путь

```text
knowledge file
  -> MemoryKnowledgeItem
  -> MemorySearchDocument
  -> search indexes
  -> memory.search
```

Для исходных данных:

```text
MemorySourceObject
  -> temporary processing
  -> MemorySearchDocument
  -> source_data search result
```

## Объем работ

- Добавить `MemorySearchDocument`.
- Перевести индексирование знания на `document_id`.
- Перевести `memory.search` с чтения chunks на чтение файлового знания через reader service.
- Перевести fallback по исходным данным на безопасные метаданные `MemorySourceObject`.
- Отключить создание `MemorySnapshot` и `MemoryChunk` в обычном пути.
- Подготовить удаление моделей, admin-классов, тестовых фабрик и старых команд.
- Обновить документацию, контракты и проверки.

## Не входит

- Финальная стратегия графового поиска.
- Новый backend векторного индекса.
- Внешний HTTP API памяти.
- Перенос аналитических срезов в DuckDB.
- Новое хранилище секретов.

## Ограничения

- Не хранить полный исходный текст в `MemorySearchDocument`.
- Не отдавать агенту исходные данные без явного запроса или fallback-политики.
- Не ослаблять проверки прав, sensitivity и trusted source.
- Не индексировать значения секретов.
- Не удалять старые таблицы без миграционной проверки.
- Использовать `./.venv/bin/python` в командах проверки.

## Критерии готовности

- После обработки `memory.remember` нет новых `MemorySnapshot` и `MemoryChunk`.
- Поиск знания работает через `MemorySearchDocument`.
- Результат знания содержит `knowledge_id`, текст и `source_refs`.
- Fallback по `source_data` возвращает только безопасные метаданные.
- Unit и e2e проверки проходят.
- Документация не называет `MemorySnapshot`/`MemoryChunk` обязательной частью памяти MVP.
