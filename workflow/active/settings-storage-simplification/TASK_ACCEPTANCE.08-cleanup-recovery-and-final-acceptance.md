# TASK_ACCEPTANCE.08 — cleanup, recovery и финальная приёмка

Решение: **APPROVE для технической реализации и тестового хоста**.

Приняты следующие результаты:

- все 14 `database_override` документов зарегистрированы; исходные 13 включены
  на тестовом хосте, а `warehouse.settings` добавлен при объединении со
  складским контуром; документы используют PostgreSQL override либо Git-default
  без runtime-зеркала;
- старые тестовые JSON-зеркала удалены по прямому разрешению владельца;
- bootstrap, architecture guard, Django gateway и agent-runtime не возвращают
  второй файловый путь чтения;
- access/workflow, status colors, AI и memory/FileHub e2e прошли;
- полный набор завершился результатом 1120 passed, 61 skipped и 218 subtests;
- PostgreSQL dump восстановлен в изолированную БД; подтверждены document/audit
  hashes, revision, матрица назначений, AI parity и memory dry-run;
- временная БД, dump и тестовая DB-ревизия удалены после проверки;
- финальное независимое Sol high ревью не нашло блокирующих дефектов.

Дополнение после объединения со складским контуром принято: четырнадцатый
документ `warehouse.settings` использует единый PostgreSQL repository, а полный
повторный набор завершился результатом 1164 passed, 61 skipped и 218 subtests.

Ограничения приёмки:

- это не разрешение на production cutover;
- production backup/retention и операционное окно остаются обязательными;
- workflow и planning не архивируются до явной пользовательской приёмки;
- HIGH-риск deidentification/PII не входит в этот пакет и остаётся открытым.
