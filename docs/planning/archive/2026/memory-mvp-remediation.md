# Active plan: исправление разрывов MVP-памяти

Статус: реализовано, ожидает финальной приемки/архивации workflow-блока.

Дата: 2026-05-21.

## Цель

Исправить три замечания ревью реализации упрощенной MVP-памяти:

- `memory.remember` должен ставить задачу в очередь, а не сохранять синхронно;
- обработанное знание должно находиться через `memory.search`;
- `MemoryBelief` не должен входить в MVP-схему и обычный путь выполнения.

## Контекст

Связанные документы:

- `docs/adr/ADR-0010-memory-mvp-simplification.md`;
- `docs/architecture/MEMORY_MVP_SIMPLIFICATION_PLAN.md`;
- `docs/architecture/MEMORY_MVP_REMEDIATION_PLAN.md`;
- `workflow/archive/2026/memory-mvp-remediation/`.

## Объем работ

- Вернуть `memory.remember` к постановке `MemoryWriteRequest` и `MemoryIndexJob` в очередь.
- Убрать синхронное сохранение из AI-инструмента.
- Доработать индексацию `MemoryKnowledgeItem`, чтобы после обработки очереди знание находилось поиском.
- Убрать `MemoryBelief` из MVP-модели/миграции/admin/services/tests или явно вывести его в отдельный будущий legacy/future слой.
- Обновить контракты инструментов.
- Обновить документацию и проверки.

## Не входит

- Перенос сообщений чата в отдельный SQLite-файл.
- Детальная стратегия графового поиска.
- Изменение внешних коннекторов.
- Новая система хранения секретов.

## Критерии приемки

- `memory.remember` возвращает `status=queued` - выполнено.
- Обработка очереди переводит запрос в `accepted` - выполнено.
- После обработки очереди `memory.search` находит сохраненное знание - выполнено.
- В обычном пути не создается `MemoryClaim`, а `MemoryBelief` не входит в MVP-схему - выполнено.
- `MemoryBelief` не создается миграцией MVP - выполнено.
- Контракты и документация согласованы с очередью - выполнено.
- Unit и e2e проверки проходят - выполнено.

## Команды проверки

```bash
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py check
./.venv/bin/python manage.py validate_architecture_contracts
./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests
./.venv/bin/python manage.py memory_eval --dry-run
npm run test:e2e
git diff --check -- . ':(exclude)BACKLOG.md'
```
