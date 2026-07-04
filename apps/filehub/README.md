# apps.filehub — File Source Auto Organization

Статус: контур заморожен решением `docs/adr/ADR-0030-memory-alignment-hybrid-knowledge-v05.md` (решение 5).

`apps.filehub` реализует режим автоупорядочивания файловых источников: stable
file identity, baseline виртуальная структура, входной каталог, статистика
использования, предложения общей структуры и безопасный managed_fs перенос
(copy/verify/quarantine/purge). Архитектура зафиксирована в
`docs/adr/ADR-0025-file-source-auto-organization.md`.

Приложение было выделено из `apps.memory` пакетом 04 workflow-блока
`memory-hybrid-knowledge-v05-alignment` как чистый перенос кода: модели,
модули `file_organization*`, management-команды `memory_file_*` и UI
(`/memory/files/`, `/memory/review/file-organization/`) переехали сюда без
функциональных изменений. Физические таблицы БД не менялись — `Meta.db_table`
каждой модели закреплен за исходным именем `memory_memoryfile*`.

## Заморозка

Развитие контура (новые функции, изменение моделей, новые backend'ы
хранения) не ведется, пока:

1. не выбран реальный пилотный файловый источник;
2. владелец продукта явно не примет решение о разморозке (см. ADR-0025,
   раздел «Статус»).

До этого момента допустимы только: исправление дефектов, перенос/переименование
кода без изменения поведения, обновление документации и зависимостей
безопасности.

## Границы

- `apps.filehub` может импортировать `apps.memory` (модели `MemorySource`,
  `MemorySourceObject`, `document_ingestion`, `security`,
  `source_text_extraction`, `storage_backends`, `policies`).
- `apps.memory` не импортирует `apps.filehub`. Связь между контурами — только
  через коды источников (`MemorySourceObject.source`), не через прямые
  импорты кода.

## Команды

```
python manage.py memory_file_organization_baseline --source-code <code> --dry-run
python manage.py memory_file_incoming_worker --source-code <code> --dry-run
python manage.py memory_file_structure_stats --source-code <code> --dry-run
python manage.py memory_file_move_worker --source-code <code> --dry-run
python manage.py memory_file_auto_organization_e2e
```
