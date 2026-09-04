# Приёмка пакета 01: инвентарь и реестр документов

Статус: **Accepted**  
Дата: 2026-08-31

## Принятый результат

- все 29 JSON value documents имеют одну доменную `ConfigDocumentSpec`;
- 18 runtime descriptors являются проверяемой compatibility projection из
  спецификаций, а не вторым источником metadata;
- реестр проверяет пути, уникальность, граф зависимостей, политики отказа,
  права и допустимые сочетания backend/storage/write policy;
- inventory работает только на чтение, не выводит payload и raw secrets,
  записывает отчёт только безопасно внутри `.local/`;
- существующий файловый reader/writer использует callable validators и граф
  спецификаций, но реальные документы не переключены на новый backend.

## Доказательства

- `manage.py test apps.settings_center.test_document_registry apps.settings_center.test_document_repository --keepdb`: 40 tests OK, 12 PostgreSQL-only пропущены;
- три существующих сценария role catalog и атомарной файловой записи: 3 tests OK;
- `manage.py validate_architecture_contracts`: успешно;
- `manage.py makemigrations --check --dry-run`: no changes;
- `git diff --check`: успешно.

## Независимая проверка

Luna xhigh дважды проверила полноту инвентаря, границы generic/domain кода,
projection, secret scan и безопасную запись отчёта. После correction cycle
закрыты замечания по callable validator, cross-document graph, Windows reparse
points, backend guard, delivery scope и полной parity descriptors.

## Остаточный риск

Пакет не меняет источник рабочих значений и потому не устраняет legacy file
drift. Риск закрывается пакетами 03–08; production cutover отдельно не разрешён.
