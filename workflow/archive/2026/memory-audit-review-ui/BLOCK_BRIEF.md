# Workflow brief: UI аудита и ревью памяти

## Цель

Подготовить реализацию рабочего UI для обработки проблем памяти, privacy/audit issues и состояния поискового индекса.

## Пользовательская ценность

Администратор должен видеть, почему документ не индексируется или требует аудита, безопасно принимать решение и запускать reindex/delete stale без ручной работы в Django Admin и без доступа к секретам.

## Методическая заметка

Очередь ревью не должна быть просто таблицей. Нужны три слоя: серверная выборка с правами доступа, сервис действий с проверками последствий и неизменяемый журнал решений. Такой подход делает UI проверяемым и не дает обойти правила secret/PII/reindex через форму.

## Архитектурные источники

- `docs/adr/ADR-0017-memory-audit-review-ui.md`;
- `docs/adr/ADR-0015-file-content-fts-vector-search.md`;
- `docs/adr/ADR-0016-memory-hybrid-ranking-profiles.md`;
- `docs/planning/active/memory-audit-review-ui.md`;
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`.

## Область чтения

- `apps.memory`;
- `apps.settings_center`;
- `apps.ai`;
- `apps.core`;
- `templates/`;
- `static/`;
- `contracts/ai/`;
- `docs/adr/`;
- `docs/planning/active/`;
- `docs/guides/`;
- `workflow/active/memory-audit-review-ui/`.

## Область будущих изменений

Будущие task packets реализации могут менять:

- `apps/memory/models.py`;
- new memory migrations;
- `apps/memory/selectors.py`;
- `apps/memory/services.py`;
- new `apps/memory/review_*` modules if keeping services separated is clearer;
- `apps/memory/views.py` or dedicated memory review views;
- `apps/memory/urls.py`;
- templates under `templates/memory/review/`;
- selected static CSS/JS only if existing styles are insufficient;
- tests under `apps/memory/tests.py` or a split memory test package;
- docs, `.desc.json` and `PROJECT_STRUCTURE.yaml`.

Runtime/generated файлы, e2e fixtures и журналы должны оставаться в `.local/` или `data/`, а не в корне репозитория.

## Не цели

- Не делать отдельную SPA в первом срезе.
- Не хранить полный извлеченный текст в Django.
- Не выводить raw secret, raw PII или raw query в UI, журнале действий, тестовых данных или документации.
- Не добавлять force-index для документов, где найдены секреты.
- Не добавлять новый внешний API ревью памяти.
- Не вводить постоянную `MemoryReviewCase` в MVP; возврат к ней требует обновления ADR-0017.

## Приемка

- ADR-0017 принят и используется как архитектурная база реализации.
- Очередь ревью строится вокруг `MemoryIngestionIssue`.
- Read-only проекция `ReviewQueueItem` используется для единых списков UI вместо постоянной `MemoryReviewCase`.
- Состояние индекса строится на диагностике `MemorySearchDocument` и создает постоянные issues только при необходимости.
- Каждое действие UI пишет неизменяемый `MemoryReviewAction`.
- Серверные права защищают видимость issue, source object, search document и audit.
- E2E покрывает ревью issue и действие по состоянию индекса.

## Команды проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.settings_center.tests apps.ai.tests
python manage.py memory_file_content_search_e2e
```
