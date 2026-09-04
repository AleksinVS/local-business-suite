# Executor report — packet 01

## Scope

Добавлены `ConfigDocumentSpec`, доменные спецификации для 29 JSON value documents,
реестр и read-only команда `settings_documents_inventory`. Compatibility reader/writer
переведён на callable validator и cross-document graph из specs, запрещает файловую
запись после смены `active_backend`; dedicated role UX сохранён. Модели, миграции и
`config/settings.py` этим пакетом не изменялись.

## Решения

- `ai.models` классифицирован как `git_static`.
- `memory.claims_policy` классифицирован как `git_static`.
- `role_rules`, `workflow_rules`, status colors, AI chat settings и operational
  memory documents отмечены `database_override`.
- analytics и integration registry отмечены `git_static` из-за отсутствия
  подтверждённого runtime writer.
- `ConfigDocumentSpec` frozen; registry предоставляет `get`, `all` и
  `by_storage_policy` и проверяет duplicate id/path.
- Security flags: допустимы только `public`, `internal`, `restricted`;
  `restricted` несовместим с тихим fallback, database override без callable
  validator запрещён; политики отказа ограничены `fail_closed` и
  `visible_default_fallback`.

## Проверки

```text
pytest apps/settings_center/test_document_registry.py --reuse-db -q: 3 passed
manage.py settings_documents_inventory --format table: успешно
```

До начала рабочее дерево уже содержало изменения в `apps/settings_center/models.py`,
ADR/architecture/planning и migration 0004; они не принадлежат этому срезу и не
изменялись. Новые файлы среза перечислены в `git status`; commit не выполнялся.

## Correction cycle

Первый дефект: первоначальная версия допускала неверные default paths для memory,
устаревшие failure policy, мутацию frozen `SettingDescriptor` и небезопасное
разрешение final symlink при `--output`. Исправлено: memory paths имеют вид
`contracts/ai/memory_*.json`, graph schema — `database_override` с
`requires_domain_workflow`, static contracts используют `git`, а override пока
явно используют `legacy_file` через `active_backend` (после cutover разрешён
`database`). SettingsRegistry строит копии через `dataclasses.replace`.

Добавлены проверки schema version, repo-relative paths, callable validators,
policy/permission/delivery/backend, зависимостей и циклов, canonical hashes,
recursive secret scan, default payloads и external/dangling symlink output.

`pytest apps/settings_center/test_document_registry.py --reuse-db -q` — **7 passed**;
inventory defaults — **29/29 valid**. Полный `apps/settings_center/tests.py`
отдельно столкнулся с внешним SQLite `database is locked`.

## Повторный correction cycle

Projection теперь переносит из spec в frozen descriptors `write_policy`,
`sensitivity`, restart/reindex и metadata (`settings_path`, callable validator,
storage/active backend, failure/delivery policy и зависимости), с parity guard
на явный набор 18 runtime IDs. AI delivery scope `django+agent_runtime` оставлен
только для tools/task_types/models; registry и chat остаются Django-only.

Inventory использует type-aware secret scan: raw password/API/private/credential,
access/refresh token и client secret отклоняются; ссылки `_env`/`_ref`/`_handle`
помечаются `reference_only`, значения не выводятся. POSIX output сохраняет
dirfd/O_NOFOLLOW атомарную запись; Windows добавлена отдельная reparse-point
проверка компонентов и непосредственная проверка перед `MoveFileExW`, с POSIX
fallback только для тестов.

Проверки: `pytest apps/settings_center/test_document_registry.py --reuse-db -q` —
**10 passed**; `pytest apps/settings_center/tests.py --reuse-db -k Registry` —
**23 passed**; `git diff --check` — успешно.

После финальных исправлений добавлены прямые проверки полной descriptor parity,
secret scan и Windows reparse/atomic-replace helper. Итоговые результаты
фиксируются в `TASK_ACCEPTANCE.01-inventory-and-document-registry.md`.

## Итог

- совместный набор registry/repository: **40 tests OK**, PostgreSQL-сценарии в
  SQLite-проходе ожидаемо пропущены;
- три регрессионных сценария role catalog/file-backed apply: **3 tests OK**;
- `validate_architecture_contracts`: успешно, **29** Git-документов и **18**
  runtime compatibility descriptors согласованы;
- `makemigrations --check --dry-run` и `git diff --check`: успешно.

Пакет принят 2026-08-31 без смены active backend реальных документов.
