# Миграция рабочих документов настроек

Статус: операционный runbook пакета 03. Production apply этим пакетом не
выполняется без отдельного окна и письменного разрешения владельца.

## Назначение и границы

Команда `settings_documents_migrate` переносит только подтверждённые изменения
legacy JSON-файлов в PostgreSQL `RuntimeSettingDocument`. Она не меняет
legacy-файлы, не удаляет их и не переключает readers. Планировщик работает
только с документами `storage_policy=database_override`.

Для runtime-файла используется legacy hash
`apps.core.contract_store.normalized_hash` (pretty JSON). В новой DB-модели
используется компактный `apps.settings_center.document_hashes.document_hash`.
Эти форматы различаются и не должны смешиваться.

## Классификации

Для каждого документа команда вычисляет default/runtime hash, schema version,
состояние env override, DB revision/hash и последнее доказательство аудита.

| Класс | Значение |
|---|---|
| `identical_default` | runtime-файл равен Git-дефолту; DB row не создаётся |
| `audited_override` | runtime отличается, а последняя успешная `SettingsChange` с тем же `setting_id` имеет `after_hash`, равный legacy runtime hash |
| `ambiguous_drift` | runtime отличается, но точного последнего audit evidence нет |
| `migration_required` | не совпала schema/default структура или файл требует отдельного преобразования |
| `env_override` | путь задан вне стандартного `data/contracts/` |
| `missing_runtime` | legacy runtime-файл отсутствует; DB row не создаётся |
| `already_imported` | DB row уже совпадает с payload и текущим Git-дефолтом |
| `conflict` | повреждён JSON/DB metadata, conflicting row или несогласованные hash |
| `security_review_required` | специальный случай `core.contract.role_rules` с drift `$defaults`/`viewer` |

`ambiguous_drift`, `migration_required`, `env_override`, `conflict` и
`security_review_required` блокируют apply. `role_rules` никогда не импортируется
этим пакетом в специальном случае security review. `git_static` не импортируется
в DB даже при наличии похожего drift.

## Планирование

Предусловие: schema migrations, включая `settings_center.0004`, уже применены.
Если таблица документов недоступна, команда завершится безопасным
`store_unavailable` и не будет трактовать отсутствие таблицы как отсутствие
override.

Режим по умолчанию — read-only:

```text
python manage.py settings_documents_migrate --plan
```

Для одного dependency-closed slice можно повторять `--document-id`:

```text
python manage.py settings_documents_migrate --plan \
  --document-id workorders.contract.status_colors \
  --document-id core.contract.workflow_rules \
  --document-id core.contract.role_rules
```

Connected dependency component должен быть выбран целиком. Неполный slice
отклоняется до чтения apply-плана. `--plan` не создаёт DB rows, audit rows,
backup или изменения runtime-файлов.

Отчёт по умолчанию печатается в stdout. `--output` разрешён только внутри
`.local/`. В отчёте нет payload и необезличенных чувствительных значений.

## Apply

Apply требует повторяемый ID, active superuser и заранее существующий backup
root:

```text
python manage.py settings_documents_migrate --apply \
  --document-id <id> \
  --actor-id <active-superuser-id> \
  --backup-root <protected-deployment-backup-root>
```

Каждый выбранный документ обязан иметь `active_backend=legacy_file`. Документ,
уже переключённый на PostgreSQL, исключается из общего plan и отклоняется при
явном выборе: повторно импортировать его замороженный legacy-файл нельзя.

`backup-root` не должен быть Git-корнем, `contracts/`, symlink или каталогом,
который команда должна создавать. Для каждого импортируемого payload до
транзакции создаются:

- canonical JSON backup;
- manifest с document ID, schema, legacy hash, compact hash, default hash;
- `manifest_hash`.

Оба файла записываются атомарно, перечитываются и проверяются. Ошибка backup
останавливает apply до DB write.

Финальный plan, чтение/backup и транзакция выполняются под общей блокировкой
legacy Settings Center writer. Затем в одной PostgreSQL-транзакции:

1. берутся transaction-level advisory locks по отсортированным ID;
2. существующие rows читаются с `select_for_update()`;
3. plan, runtime-файл, audit evidence и Git-дефолт перепроверяются после locks;
4. payload валидируется и проверяется на raw secrets;
5. создаётся `RuntimeSettingDocument` с revision `1`;
6. создаётся применённая `SettingsChange` с masked diff, audit context и
   `document_revision_after=1`.

Если любой документ не проходит проверку, транзакция откатывает весь slice.
PostgreSQL обязателен: SQLite не предоставляет нужных advisory-lock гарантий.

Повторный apply не увеличивает revision и не создаёт новую audit row, если
существующая DB row совпадает с payload, content hash и default hash. Row с
повреждёнными metadata или иным payload классифицируется как conflict.

На Windows разрешён только read-only plan в stdout. `--apply`, export и запись
отчёта в файл завершаются закрытым отказом: текущая реализация не заявляет
гарантии, эквивалентные POSIX `O_NOFOLLOW`/dirfd. Для мутационной операции нужен
Linux deployment host либо отдельная handle-based реализация и приёмка Windows.

## Export

Экспортирует effective payload и manifest:

```text
python manage.py settings_documents_export \
  --document-id <id> \
  --output .local/settings-export/<id>.json
```

Вывод вне `.local/` требует существующего защищённого каталога:

```text
python manage.py settings_documents_export \
  --document-id <id> \
  --output <operator-root>/<id>.json \
  --operator-output-root <operator-root>
```

Export JSON canonical и содержит полный effective payload. Manifest содержит
source (`git_default`/`database_override`), revision, schema, content/default
hash и проверяемый `manifest_hash`. Secret-bearing документы не регистрируются;
отчёты и stdout не печатают payload.

## Rollback и восстановление

Backup является защищённой копией и доказательством операции, а не новым
источником чтения. До DB cutover оператор может восстановить legacy-файл только
по отдельной проверенной процедуре. После появления DB revision нельзя копировать
старый backup поверх runtime-файла: это не изменит PostgreSQL effective state.

После cutover rollback выполняется через document writer как новая revision и
новая `SettingsChange` с `rollback_of`. Legacy-файлы не удаляются автоматически.

## Проверки и health

Перед операционным окном:

```text
python manage.py validate_architecture_contracts
make verify-profile PROFILE=contracts
make verify-profile PROFILE=deployment
```

Health/check должен показывать `migration_required`, `ambiguous_legacy`,
`env_override`, `conflict` и `security_review_required`; ошибка таблицы/БД
показывается как безопасный `store_unavailable`, прочая ошибка планировщика —
как `migration_unavailable`. Эти состояния не исправляются
автоматически и не раскрывают payload, пути или текст исключения.

До запуска apply необходимо зафиксировать freeze legacy writers, получить новый
plan, проверить backup root и сохранить stdout/report в `.local/`. После apply
проверить количество rows/audit, hashes, health и smoke-сценарии потребителей.
