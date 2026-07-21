# Workflow brief: файловые знания, раздельные базы и единый поиск

Статус: active.

Дата: 2026-05-22.

## Цель

Реализовать переход системы памяти к целевой схеме:

- принятые знания хранятся в файлах и Git;
- данные остаются в источниках;
- временные слои обработки удаляются;
- метаданные, индексы, чаты и аналитика разделены;
- поиск знаний и файлового хранилища идет через единый сервис.

## Архитектурные источники

- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/architecture/MEMORY_FILE_BACKED_KNOWLEDGE_PLAN.md`;
- `docs/planning/active/memory-file-backed-knowledge.md`;
- `docs/adr/ADR-0010-memory-mvp-simplification.md`.

## Write scope

Основной scope:

- `apps/memory/`;
- `apps/ai/`;
- `apps/analytics/`;
- `config/settings.py`;
- `contracts/ai/`;
- `contracts/schemas/`;
- `docs/`;
- `workflow/active/memory-file-backed-knowledge/`;
- `PROJECT_STRUCTURE.yaml`.

Runtime-данные:

- использовать только `data/`;
- временные тестовые файлы писать в `.local/`;
- не коммитить `data/knowledge_repo/` и другие runtime-данные.

## Non-goals

- Не внедрять внешний публичный API памяти.
- Не менять секреты и secret handles.
- Не переносить все legacy-модели одним рискованным изменением.
- Не выбирать окончательный production backend векторного индекса.
- Не ослаблять права доступа и проверку источников.

## Риски

- Потеря или дублирование знаний при миграции из базы в файлы.
- Несогласованность Git-файлов и metadata database.
- Ошибки маршрутизации нескольких SQLite-баз.
- Утечка исходных данных в индекс или временную зону.
- Слишком тяжелая логика поиска для локальной модели.

## Обязательные проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests apps.analytics.tests
python manage.py memory_eval --dry-run
npm run test:e2e
```

Для каждого крупного task packet нужен отдельный unit или integration test. Для блока целиком нужен e2e-сценарий: `memory.remember` -> writer queue -> файл знания -> индекс -> поиск -> source link.
