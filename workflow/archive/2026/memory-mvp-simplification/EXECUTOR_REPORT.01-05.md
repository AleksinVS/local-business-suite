# Executor report: memory MVP simplification

Дата: 2026-05-21.

## Выполнено

- `MemoryKnowledgeItem` закреплен как главный результат обычного `memory.remember`.
- AI tool `memory.remember` теперь сохраняет знание и возвращает `memory_id`, `event_id`, `processed_at`.
- Очередь `MemoryWriteRequest` сохранена для совместимости и обработки уже поставленных requests.
- Автоматическое создание `MemoryClaim` и `MemoryBelief` в обычном remember path отключено.
- `memory.search` больше не ищет и не возвращает `memory_belief`.
- Счетчики команды `memory_reflect_chats` переведены с accepted beliefs на active knowledge items.
- Help text `memory_reflect_chats` уточнен: это совместимый обработчик очереди, не полноценная ночная рефлексия.
- Политика надежности источников сведена к MVP-схеме `trusted`, `review_required`, `blocked`.
- Старые `candidate_only` и `quarantined` совместимо отображаются в `review_required`.
- Документация, контракты и тесты синхронизированы с ADR-0010.

## MemoryClaim

`MemoryClaim` оставлен в модели и admin visibility как заготовка для будущих проверок спорных утверждений. В обычном `memory.remember` автоматическое создание отключено, потому что для MVP главным объектом памяти является `MemoryKnowledgeItem`, а claim layer не нужен для сохранения явного пользовательского знания.

## Совместимость

- Модели `MemoryClaim` и `MemoryBelief` не удалялись, чтобы не терять уже созданные данные.
- `MemorySource.TrustStatus` принимает новый `review_required` и старые `candidate_only` / `quarantined`.
- `effective_source_trust()` возвращает нормализованный MVP-статус и сохраняет `raw_trust_status` для диагностики.
- Runtime contracts в `data/contracts/ai/tools.json` обновлены вместе с дефолтным `contracts/ai/tools.json`, чтобы локальная проверка контрактов проходила без ручной синхронизации.

## Проверки

- `.venv/bin/python manage.py makemigrations --check --dry-run`
- `.venv/bin/python manage.py check`
- `.venv/bin/python manage.py validate_architecture_contracts`
- `.venv/bin/python manage.py test apps.memory.tests apps.ai.tests`
- `.venv/bin/python manage.py memory_eval --dry-run`
- `npm run test:e2e`
- `git diff --check -- . ':(exclude)BACKLOG.md'`

Примечание: команда `python ...` в этой среде не доступна (`python: command not found`), поэтому те же проверки выполнены через `.venv/bin/python`.
