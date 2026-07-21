# Executor report: memory MVP remediation 01-04

Дата: 2026-05-21.

## Срезы

1. `01-remember-queues-request` - выполнено.
   `memory.remember` в AI runtime вызывает `queue_memory_remember_for_actor`, возвращает `status=queued`, `request_id`, `job_id`, `target_scope`, `queued_at` и не создает `MemoryKnowledgeItem` синхронно.
2. `02-processed-memory-is-searchable` - выполнено.
   Обработчик очереди создает `MemoryKnowledgeItem`, `MemorySnapshot` и `MemoryChunk`, индексирует chunk в стандартный `SQLiteFTSMemoryBackend`; после обработки `memory.search` находит сохраненный `memory_chunk`.
3. `03-remove-memory-belief-from-mvp` - выполнено.
   `MemoryBelief` удален из модели, миграции MVP, admin-регистрации, обычных сервисов и MVP-тестов. `MemoryClaim` оставлен как будущая заготовка, но обычный remember path его не создает.
4. `04-contracts-docs-tests-acceptance` - выполнено.
   Канонический и runtime tool contracts описывают queued-ответ. Документация синхронизирована с очередью, поиском после обработки и выводом `MemoryBelief` из MVP.

## Измененные области

- AI tool dispatch и tool contracts.
- Chat memory queue processing и индексация обработанных knowledge items.
- Memory models/admin/migration/services/tests.
- Memory user/deployment/architecture/planning docs.
- Workflow task packet statuses and acceptance artifacts.

## Проверки

| Команда | Результат |
| --- | --- |
| `./.venv/bin/python manage.py makemigrations --check --dry-run` | PASS |
| `./.venv/bin/python manage.py check` | PASS |
| `./.venv/bin/python manage.py validate_architecture_contracts` | PASS |
| `./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests` | PASS, 103 tests |
| `./.venv/bin/python manage.py memory_eval --dry-run` | PASS, passed=6 failed=0 |
| `npm run test:e2e` | PASS, 1 test |
| `make gen-struct` | PASS |
| `git diff --check -- . ':(exclude)BACKLOG.md'` | PASS |

## Остаточные риски

- Если таблица `MemoryBelief` уже применялась в отдельной среде, ее удаление из текущей MVP-ветки потребует отдельной безопасной deployment-процедуры для этой среды.
- Runtime-копии контрактов в `data/contracts/` нужно синхронизировать при деплое так же, как сделано локально для проверки.
