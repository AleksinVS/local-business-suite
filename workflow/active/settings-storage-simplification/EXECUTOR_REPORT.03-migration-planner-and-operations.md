# Отчёт исполнения — пакет 03

## Объём

Реализованы безопасные plan/apply/export для переноса подтверждённых legacy
JSON overrides в `RuntimeSettingDocument`. Production apply не выполнялся,
legacy-файлы и основная БД не изменялись.

Основные файлы:

- `apps/settings_center/document_migration.py`;
- команды `settings_documents_migrate` и `settings_documents_export`;
- `apps/settings_center/checks.py` и health-интеграция;
- `apps/settings_center/test_document_migration.py`;
- `apps/settings_center/test_document_migration_health.py`;
- `docs/deployment/SETTINGS_DOCUMENTS_MIGRATION.md`.

## Реализация

- `--plan` является режимом по умолчанию и не пишет в БД/файлы.
- Apply принимает только полный связный срез, требует активного superuser,
  PostgreSQL и существующий backup-root вне проекта.
- `identical_default` и `missing_runtime` — успешные no-op; импортируется только
  `audited_override`. Неоднозначные, конфликтные, env/schema/security состояния
  блокируют весь срез.
- Доказательством служит только последняя применённая запись того же document ID
  с точным legacy normalized hash. Более новая несовпадающая запись отменяет
  доказательство; rollback учитывается как версия.
- Legacy и compact hashes разделены. Raw secrets запрещены единым gate для
  default/runtime/DB, backup, export и audit context.
- Общая файловая блокировка legacy writer удерживается от финального plan до
  завершения PostgreSQL-транзакции; после advisory/select locks файлы, аудит и
  DB-состояние перепроверяются.
- POSIX-чтение/запись и lock-файл используют component-wise
  `O_NOFOLLOW`/dirfd; после получения блокировки проверяется неизменность inode.
  Dangling/parent symlink классифицируются как conflict. На Windows apply,
  export и файловый отчёт закрыты отказом; доступен только stdout-plan.
- Backup имеет уникальные имена, canonical payload, manifest и post-write hash
  verification. Export запрещает одинаковые payload/manifest пути, не
  перезаписывает доказательства и удаляет только созданный им неполный вывод.
- Health и system check показывают безопасные коды без payload, путей и текстов
  исключений: `migration_required`, `ambiguous_legacy`, `env_override`,
  `conflict`, `security_review_required`, `store_unavailable`,
  `migration_unavailable`.

## Проверки

Финальная ступенчатая проверка выполнена основным агентом на сохраняемой
PostgreSQL test DB:

```text
make verify-fast TEST_SCOPE=<registry/repository/migration/health/pilot>
112 passed, 2 skipped, 19 subtests passed
```

Пропуски относятся к платформенно-зависимым сценариям. Набор проверяет
успешные команды apply/export,
идемпотентность без новой audit row, полный rollback двухдокументного среза,
варианты secret-полей и межпроцессную/ссылочную защиту lock-файла.
Дополнительно успешны `compileall` и `git diff --check`.

Read-only запуск плана на основной PostgreSQL БД корректно остановился кодом
`store_unavailable`: schema migration `settings_center.0004` там ещё не
применена. Это ожидаемый deployment gate; миграции и строки не создавались.

## Остаточные риски

1. Production plan/apply требует отдельного окна, backup-root и разрешения
   владельца; пакет этого не выполняет.
2. Backup создаётся до DB transaction и при позднем rollback сохраняется как
   операторское доказательство, а не удаляется автоматически.
3. Мутационные команды пакета на Windows не поддерживаются. До реализации
   handle-based no-follow записи оператор может использовать только stdout-plan
   и выполнять apply/export с Linux deployment host.
4. PostgreSQL и файловая система не образуют общей транзакции. Все portal writers
   используют общий неизменяемый lock, а runtime-каталог должен быть доступен
   только service account; прямое вмешательство тем же системным пользователем
   считается операционным нарушением и требует нового plan.
