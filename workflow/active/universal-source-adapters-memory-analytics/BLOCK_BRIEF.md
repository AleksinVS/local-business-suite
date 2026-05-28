# Workflow brief: универсальные источники для памяти и аналитики

## Цель

Подготовить и реализовать единый подход подключения источников к памяти и аналитике: внутренние модули, файлы, внешние API и будущие расширения должны отдавать нормализованный `SourceObjectEnvelope`, из которого строятся поисковые и аналитические проекции.

## Пользовательская ценность

ИИ-бот и аналитика смогут работать с данными канбана, листа ожидания, файлов и API одинаково, без прямой зависимости памяти от конкретных Django-моделей. Новые модули можно будет добавлять и удалять без поломки памяти, поиска и аналитики.

## Методическая заметка

Здесь источник истины и производная проекция разделяются. Доменный модуль владеет бизнес-объектом и правами доступа, а память и аналитика получают нормализованный envelope. Это снижает связность и оставляет возможность позже перейти к event-driven синхронизации.

## Архитектурные источники

- `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`;
- `docs/planning/active/universal-source-adapters-memory-analytics.md`;
- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/adr/ADR-0015-file-content-fts-vector-search.md`;
- `docs/adr/ADR-0016-memory-hybrid-ranking-profiles.md`;
- `docs/adr/ADR-0008-knowledge-driven-business-analytics.md`;
- `docs/architecture/KNOWLEDGE_DRIVEN_ANALYTICS_PLAN.md`;
- `docs/architecture/MEMORY_MVP_CURRENT_STATE.md`.

## Область чтения

- `apps/core`;
- `apps/memory`;
- `apps/analytics`;
- `apps/workorders`;
- `apps/waiting_list`;
- `apps/ai`;
- `contracts/ai`;
- `contracts/analytics`;
- `docs/adr`;
- `docs/architecture`;
- `docs/planning`;
- `workflow/active/universal-source-adapters-memory-analytics/`.

## Область будущих изменений

Будущие task packets могут менять:

- `apps/core/source_adapters.py` или близкий общий модуль;
- `apps/core/json_utils.py`;
- `apps/memory/*`;
- `apps/analytics/*`;
- `apps/workorders/source_adapter.py`;
- `apps/waiting_list/source_adapter.py`;
- management commands для sync/reconcile;
- `contracts/ai/memory_sources.json`;
- `contracts/analytics/sources.json`;
- новые schema/contract файлы, если они будут приняты ADR;
- `apps/ai/tool_definitions.py` и `contracts/ai/tools.json`, если добавляется доменный search wrapper;
- tests под затронутыми apps;
- docs, `.desc.json`, `PROJECT_STRUCTURE.yaml`.

Runtime/generated файлы, e2e fixtures и журналы должны оставаться в `.local/` или `data/`, а не в корне репозитория.

## Не цели

- Не строить универсальный event bus/outbox в MVP.
- Не объединять `MemorySource` и `AnalyticsSource` в одну таблицу.
- Не делать внешний HTTP API источников.
- Не превращать все source_data в accepted knowledge.
- Не хранить полный исходный объект в metadata поискового документа.
- Не отключать secret scanning через PII policy.

## Приемка

- ADR-0018 принят или обновлен по итогам owner review.
- Есть единый envelope contract и adapter protocol.
- PII defaults реализованы: по умолчанию off, external guarded, PII audit выключен при off.
- Secret scanning остается всегда включенным.
- Memory projection и analytics projection строятся из envelope.
- `workorders` и `waiting_list` подключены через адаптеры.
- Access policy `adapter_check` выполняет финальную серверную проверку перед выдачей source_data.
- Reconcile поддерживает upsert/delete и missing adapter fail-closed.
- E2E покрывает поиск, права, privacy defaults и аналитический факт.

## Команды проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.core.tests apps.memory.tests apps.analytics.tests apps.workorders.tests apps.waiting_list.tests apps.ai.tests
python manage.py memory_file_content_search_e2e
python manage.py analytics_recalculate_metrics --dry-run
```
