# Отчёт исполнения — пакет 04

Статус: **реализация dev/test завершена; production cutover не выполнялся**.

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

## Невыполненный эксплуатационный шлюз

Production allowlist не менялся, рабочая БД и `data/contracts/` не затрагивались.
Для фактического переключения ещё нужны применённая schema migration,
read-only plan без неоднозначного drift, защищённая резервная копия,
согласованное окно наблюдения и отдельное разрешение владельца. До этого пакет
не считается production cutover.
