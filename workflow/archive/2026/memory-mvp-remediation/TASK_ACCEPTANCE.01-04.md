# Task acceptance: memory MVP remediation 01-04

Дата: 2026-05-21.

## Приемка

- `memory.remember` возвращает `queued`, а не `accepted` - принято.
- После первичного вызова создаются `MemoryWriteRequest` и `MemoryIndexJob`, но не создается `MemoryKnowledgeItem` - принято.
- Обработчик очереди переводит request в `accepted` и закрывает job как `succeeded` - принято.
- После обработки `memory.search` находит сохраненный `memory_chunk` - принято.
- Обычный remember path не создает `MemoryClaim` - принято.
- `MemoryBelief` не входит в MVP-модель, миграцию, admin и обычный runtime path - принято.
- Секретное значение не попадает в сохраненный текст, search result и стандартный FTS index - принято.
- Контракты и документация больше не обещают `memory_id`, `event_id` или `processed_at` в первичном ответе `memory.remember` - принято.

## Проверки

Принято по результатам:

- `./.venv/bin/python manage.py makemigrations --check --dry-run`;
- `./.venv/bin/python manage.py check`;
- `./.venv/bin/python manage.py validate_architecture_contracts`;
- `./.venv/bin/python manage.py test apps.memory.tests apps.ai.tests`;
- `./.venv/bin/python manage.py memory_eval --dry-run`;
- `npm run test:e2e`.

`make gen-struct` и `git diff --check -- . ':(exclude)BACKLOG.md'` выполнены после добавления workflow-отчетов.

## Решение

Приемка срезов 01-04 выполнена на уровне исполнителя. Финальная приемка и архивирование workflow-блока остаются за владельцем/оркестратором.
