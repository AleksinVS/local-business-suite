# TASK_ACCEPTANCE.07 — memory/FileHub и статическая классификация

Решение: **APPROVE для технической реализации и тестового среза**.

По `EXECUTOR_REPORT.07-memory-filehub-and-static-classification.md` memory и
FileHub получают immutable operation/job snapshots; source lifecycle и retrieval
закрываются при stale/missing contract; FileHub current file chain проверяется
единым fail-closed helper до создания job и повторно перед физическим I/O.
Analytics, integration registry и claims policy классифицированы как
`git_static`; восемь memory документов выпущены как database_override. Durable
outbox для `requires_reindex` создаётся в той же транзакции после документа и
`SettingsChange`, а тяжёлая работа выполняется только worker-ом после commit.

Основной агент передал результаты PostgreSQL: 33 settings/snapshot/source
теста, широкий PG FileHub/analytics/ingestion/privacy и host git/AI identity
наборы зелёные; постоянный `memory_file_auto_organization_e2e` прошёл. В main
исправлены `IndexStatus.PENDING` и scoped identity fixtures. Локальные узкие
проверки выполнены с `--reuse-db`; PostgreSQL здесь не запускался.

Ограничения решения:

- приватный deployment allowlist не изменялся и production cutover не объявлен;
- recovery drill и полный `make verify-full` выполняются в package08;
- bootstrap deidentification/PII остаётся отдельным существующим HIGH-риском,
  не входит в scope и не разрешает передачу ПДн во внешние сервисы;
- acceptance означает техническую готовность, не удаление legacy backup.
