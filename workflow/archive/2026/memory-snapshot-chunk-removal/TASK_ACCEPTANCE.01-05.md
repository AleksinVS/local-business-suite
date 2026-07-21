# Task Acceptance: memory-snapshot-chunk-removal

Дата: 2026-05-22.

## Приемка

Принято.

## Проверенные критерии

- `memory.remember` после обработки очереди создает файл знания, `MemoryKnowledgeItem` и `MemorySearchDocument`.
- `MemorySnapshot`, `MemoryChunk` и привязанный к ним `MemoryGraphFact` удалены из текущей модели Django.
- `memory.search` возвращает `knowledge_id`, текст знания, `source_refs` и citations через `MemorySearchDocument`.
- Fallback в `source_data` возвращает безопасные метаданные и ссылку на исходный объект.
- Админка показывает `MemorySearchDocument` вместо рабочих разделов snapshots/chunks.
- Unit и e2e проверки прошли.

## Принятый компромисс

Графовый поиск временно выключен до отдельной стратегии графового индекса. Это согласуется с границами блока: текущая задача убирает лишний слой снимков/фрагментов, но не проектирует новый графовый поиск.
