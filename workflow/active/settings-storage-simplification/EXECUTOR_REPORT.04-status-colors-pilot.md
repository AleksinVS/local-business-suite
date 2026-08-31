# Отчёт исполнения — пакет 04

Статус: **реализация dev/test завершена; production cutover заблокирован
решением по legacy-данным**.

## Результат

Выпущен закрытый по умолчанию DB backend только для
`waiting_list.contract.status_colors`. Переменная
`LOCAL_BUSINESS_SETTINGS_DOCUMENT_DB_ALLOWLIST` пуста по умолчанию и принимает
только известные выпущенные ID и полный связанный срез. Неизвестные ID,
wildcard, дубли и неполные зависимости завершают запуск закрытым отказом.

Палитра заявок `workorders.contract.status_colors` остаётся на legacy backend и
не менялась. Документы не объединены и сохраняют отдельные revision, аудит и
rollback.

## Реализация

- совместимый `get_contract("waiting_list_status_colors")` маршрутизируется в
  repository только при включённом pilot ID;
- чтение использует request-local снимок, следующий запрос другого процесса
  видит новую ревизию без перезапуска;
- форма передаёт ожидаемые `base_revision` и `base_hash`;
- запись идёт через `ConfigDocumentWriter`, создаёт точную `SettingsChange` и не
  переписывает legacy-файл;
- rollback создаёт следующую ревизию и отдельный audit event;
- повреждённая строка даёт видимый Git-default fallback, сигнал деградации и
  запрещает запись поверх повреждения;
- migration health больше не сравнивает уже активный DB-документ с замороженным
  legacy-файлом;
- пользовательский экран листа ожидания получает фактически настроенные цвета.

## Проверки

Основной агент выполнил на существующей PostgreSQL test DB с `--keepdb`
совместный набор repository, migration, health, file-lock и pilot:

```text
make verify-fast TEST_SCOPE=<registry/repository/migration/health/pilot>
112 passed, 2 skipped, 19 subtests passed
```

Профиль контрактов дополнительно дал 52 passed, профиль развёртывания — 29
passed; `makemigrations --check --dry-run` не нашёл изменений. Пилотный набор
покрывает routing/default, HTTP-отображение цветов, HTTP-запись,
неизменность legacy-файла, stale conflict, независимое чтение следующей
ревизии, rollback и видимую деградацию повреждённой строки. `git diff --check`
и `compileall` успешны.

Полный профиль UI на PostgreSQL остановился до browser smoke на существующем
AI-тесте replay: JSONB меняет порядок ключей события, а тест сравнивает SSE как
байты. Тот же тест проходит на SQLite; затронутые файлы AI не изменялись.
Проблема не относится к пилоту настроек и зафиксирована как остаточная проверка,
а не исправлена расширением write scope.

## Независимое ревью

Luna xhigh вынесла verdict **approve** для dev/test реализации. Единственное
замечание — ложный migration health после штатной DB-записи — исправлено:
активные DB-документы исключены из legacy migration probe и добавлен отдельный
регрессионный тест.

## Production preflight 2026-08-31

Собран воспроизводимый image из чистого commit `5f75248` с OCI revision label;
предыдущий image сохранён отдельным rollback-тегом. Compose resolution подтвердил
рабочий mount `/home/abc/projects/local-business-suite/data:/app/data`, пустой
allowlist и отсутствие дополнительных Django workers. `bootstrap_runtime
--dry-run` не запланировал изменений, проверка контрактов нового image не дала
ошибок.

До изменения schema созданы и проверены:

- PostgreSQL custom dump;
- побайтовая копия legacy-палитры с SHA-256;
- защищённая копия приватного env.

Операторский каталог:
`/home/abc/.local-backups/local-business-suite/settings-pilot-5f75248-20260831`.
Payload и секреты в отчёт не включены.

Реальный migration plan дополнительно показал параллельные `ai.0014`,
`inventory.0010` и `waiting_list.0006`. После Sol high review отдельным
schema-only окном применены:

- `settings_center.0004` — новая таблица документов и nullable audit metadata;
- `ai.0014` — новая пустая таблица `ChatRun`;
- `inventory.0010` — `varchar` в `text` для таблицы из шести строк.

`waiting_list.0006` намеренно не применялась. В БД остаются две записи
`service_id=s1`, созданные при старом каталоге услуг. Новый код переиспользует
`s1` для несвязанной офтальмологической услуги, а миграция данных отсутствует.
Удалять записи или угадывать соответствие без решения владельца запрещено.

Состояние после окна:

- старый web image запущен напрямую через Gunicorn и отвечает `/health/`;
- agent-runtime `/health` отвечает;
- `RuntimeSettingDocument` rows: 0;
- allowlist отсутствует;
- legacy-файл не изменён;
- `waiting_list.0006` остаётся pending.

Прямой Gunicorn — временное восстановление предыдущего runtime: штатный startup
старого image теперь блокируется существующим `core.E001`, потому что рабочий
реестр AI-инструментов уже новее образа. Этот режим нельзя считать завершённым
deployment; он сохраняет доступность test-host до решения по данным и запуска
нового совместимого image.

## Невыполненный эксплуатационный шлюз

Production allowlist не менялся, `data/contracts/` не затрагивался. Для
фактического переключения ещё нужны решение владельца по двум legacy-записям,
применение `waiting_list.0006`, final plan `identical_default`, freeze, export,
smoke и read-only окно наблюдения. До этого пакет не считается production
cutover.
