# Workflow brief: автоупорядочивание файловых источников

## Цель

Подготовить и реализовать режим автоупорядочивания файлового источника: виртуальная структура сначала, входной каталог для новых файлов, автоматический baseline после первичного анализа, статистика пользовательских структур, согласованный физический перенос в managed root и готовность к будущему S3-compatible backend.

## Пользовательская ценность

Пользователь видит порядок и может работать с личными виртуальными папками без немедленного риска для исходного хранилища. Администратор получает объяснимые предложения и переносит файлы физически только после статистики, review и проверок. Система постепенно уменьшает хаос и может экономить место после безопасного удаления исходников.

## Методическая заметка

В этом блоке путь файла считается адресом, а не идентификатором. Стабильный `file_id`, версии содержимого, физические размещения и виртуальные представления проектируются отдельно. Это позволяет строить виртуальные структуры, выполнять физический перенос и позже перейти к S3 без смены пользовательской модели.

## Архитектурные источники

- `docs/adr/ADR-0025-file-source-auto-organization.md`;
- `docs/architecture/MEMORY_FILE_SOURCE_AUTO_ORGANIZATION_PLAN.md`;
- `docs/planning/archive/2026/memory-file-source-auto-organization.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0011-file-backed-knowledge-and-unified-search.md`;
- `docs/adr/ADR-0018-universal-source-adapters-memory-analytics.md`;
- `docs/guides/MEMORY_INGESTION_OPERATIONS.md`;
- `docs/guides/WORKER_AND_QUEUE_OPERATIONS.md`.

## Область чтения

- `apps/memory`;
- `apps/ai`;
- `apps/core`;
- `contracts/ai`;
- `contracts/schemas`;
- `docs/adr`;
- `docs/architecture`;
- `docs/guides`;
- `docs/planning`;
- `workflow/archive/2026/memory-file-source-auto-organization/`.

## Область будущих изменений

Будущие task packets могут менять:

- `apps/memory/models.py`;
- `apps/memory/document_ingestion.py`;
- новые сервисы `apps/memory/file_organization*.py`;
- management commands для baseline, incoming worker, stats, move worker и e2e;
- `apps/memory/views.py`, `review_selectors.py`, `review_services.py`, templates и urls для UI;
- `apps/memory/tests.py` или отдельные test modules;
- `apps/core/json_utils.py`;
- `contracts/ai/memory_file_organization_profiles.json`;
- `contracts/schemas/memory_file_organization_profiles.schema.json`;
- `contracts/role_rules.json`, если нужно уточнить роли;
- `docs/deployment`, `docs/guides`, `docs/architecture`, `docs/planning`;
- `.desc.json` и `PROJECT_STRUCTURE.yaml`.

Runtime paths, generated manifests, move logs, synthetic file corpora and e2e artifacts must stay under `.local/` or `data/`, not in the repository root.

## Не цели

- Не внедрять S3 в MVP.
- Не выполнять физический перенос до owner/admin approval.
- Не удалять исходники без quarantine/retention и backup checkpoint.
- Не использовать relative path как stable file identity.
- Не давать user virtual views обходить source access policy.
- Не хранить raw content, secrets, PII или полные чувствительные UNC paths в audit/events.
- Не сканировать полный unmanaged corporate share без утвержденного source scope.

## Приемка

- ADR-0025 принят.
- Есть stable file identity, path history и version model.
- Baseline virtual structure создается после primary analysis и имеет confidence/evidence/conflicts.
- Incoming folder работает через worker и review queue.
- User virtual views сохраняются отдельно от физического размещения.
- Usage statistics создает organization proposals только из агрегированных safe-сигналов.
- Managed physical transfer выполняет copy/verify/metadata commit/quarantine/purge.
- Source purge невозможен без retention и backup checkpoint.
- StorageBackend interface готов к future S3-compatible backend.
- Unit и e2e проверки покрывают baseline, incoming, proposals, move safety и access control.

## Команды проверки

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.memory.tests apps.ai.tests
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py memory_file_auto_organization_e2e
```
