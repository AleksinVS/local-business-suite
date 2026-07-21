# Retrospective: memory MVP remediation

Дата: 2026-05-21.

## Что изменилось

- Очередь стала единственным обычным путем `memory.remember`.
- Обработанная память стала доступна через обычный `memory.search` без отдельного тестового backend.
- `MemoryBelief` выведен из MVP-схемы текущей ветки, а `MemoryClaim` оставлен только как будущий слой.

## Что сработало

- Проверка `makemigrations --check --dry-run` сразу подтвердила, что модель и миграция согласованы после удаления `MemoryBelief`.
- Полный тестовый путь `queued -> accepted -> searchable` выявил и закрепил нужную точку индексации: `index_knowledge_item` должен писать в default FTS backend.
- `validate_architecture_contracts` поймал устаревшую runtime-копию `data/contracts/ai/tools.json`, а не только default-контракт.

## Что учесть дальше

- Runtime-контракты в `data/contracts/` могут расходиться с `contracts/`; для deployment нужна явная синхронизация после backup.
- Если какая-то среда уже применяла таблицу `MemoryBelief`, удаление из этой среды нужно оформлять отдельной безопасной миграцией/процедурой.
- Будущий claim/belief governance должен оставаться отдельным этапом, чтобы не размывать MVP remember/search path.
