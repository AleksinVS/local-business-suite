# Executor report: автоупорядочивание файловых источников

Дата: 2026-06-02.

## Выполнено

- ADR-0025 переведен в `Accepted`.
- Добавлены модели stable file identity, versions, physical placements, path aliases, virtual views/rules/placements, usage events, proposals/decisions и move jobs.
- Добавлен default/runtime contract `memory_file_organization_profiles.json` и JSON Schema.
- Добавлены валидаторы контрактов, настройки Django и descriptor Settings Center.
- Реализованы сервисы:
  - `file_organization.py`;
  - `file_organization_baseline.py`;
  - `file_organization_incoming.py`;
  - `file_organization_stats.py`;
  - `storage_backends.py`;
  - `file_organization_move.py`.
- Добавлены management commands:
  - `memory_file_organization_baseline`;
  - `memory_file_incoming_worker`;
  - `memory_file_structure_stats`;
  - `memory_file_move_worker`;
  - `memory_file_auto_organization_e2e`.
- Добавлен UI `/memory/review/file-organization/`.
- Добавлен пользовательский UI `/memory/files/` для личных виртуальных размещений доступных файлов.
- Обновлены deployment, user и ingestion guides, текущая граница MVP и planning/backlog.

## Ограничения MVP

- S3-compatible backend не реализован как runtime-зависимость.
- Пользовательский UI реализован как минимальный экран создания личных виртуальных размещений; расширенный редактор дерева остается будущим улучшением.
- Physical move выполняется только через `managed_fs` и approved move jobs.
- Purge исходника разрешен только после quarantine/retention и backup checkpoint при включенной политике.

## Проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.memory.tests.MemoryFileAutoOrganizationTests apps.core.tests.ArchitectureContractTests
.venv/bin/python manage.py memory_file_auto_organization_e2e
.venv/bin/python manage.py test apps.memory.tests
.venv/bin/python manage.py test apps.settings_center.tests
```

Все команды прошли успешно после применения миграции `memory.0013` в runtime `knowledge_meta` для e2e-команды.

## Runtime note

Локально для запуска e2e была применена миграция:

```bash
.venv/bin/python manage.py migrate --database=knowledge_meta
```

В production это должно выполняться стандартным deployment entrypoint для всех runtime database aliases.
