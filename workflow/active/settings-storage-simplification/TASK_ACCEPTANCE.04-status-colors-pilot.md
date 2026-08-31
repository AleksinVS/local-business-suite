# Приёмка пакета 04: палитра листа ожидания

Статус: **Accepted for dev/test; production cutover blocked on data decision**
Дата: 2026-08-31

## Принятый результат

- DB backend выпущен только для `waiting_list.contract.status_colors` и закрыт
  пустым по умолчанию deployment allowlist;
- UI читает request-local snapshot, пишет с revision/hash CAS и показывает
  stale conflict, rollback и видимую деградацию;
- следующий запрос другого процесса видит новую ревизию без restart;
- legacy-файл палитры листа ожидания не переписывается;
- `workorders.contract.status_colors` остаётся legacy и не объединяется с
  пилотным документом;
- migration health не сравнивает активный DB-документ с замороженным legacy.

## Доказательства

- общий PostgreSQL `verify-fast`: 112 passed, 2 skipped, 19 subtests passed;
- постоянные HTTP-сценарии проверяют страницу настроек и фактические цвета в
  интерфейсе листа ожидания;
- PostgreSQL-сценарии проверяют запись, stale conflict, независимое чтение,
  rollback, аудит, fallback и неизменность legacy-файла;
- профили контрактов и развёртывания успешны.

UI-профиль на PostgreSQL остановлен существующим AI replay-тестом, который
сравнивает порядок JSONB-ключей как байты; на SQLite этот тест проходит. Поэтому
browser smoke профиля не запускался. Сквозной сценарий самого пилота проверен
постоянными Django HTTP-тестами, а AI-несоответствие оставлено вне write scope.

## Независимая проверка

Luna xhigh вынесла verdict **approve** для dev/test. Замечание о ложном health
после DB-записи исправлено и покрыто тестом.

## Production preflight 2026-08-31

Sol high сначала запросил уточнение cutover/rollback runbook. После исправления
документации повторная проверка дала `approve` для test-only хоста. Реальный
`migrate --plan` затем обнаружил параллельные миграции `ai.0014`,
`inventory.0010` и `waiting_list.0006`.

`settings_center.0004`, `ai.0014` и `inventory.0010` применены отдельным
schema-only окном после проверяемого PostgreSQL dump и копии legacy-палитры.
Они обратно совместимы со старым web image. `waiting_list.0006` не применялась,
allowlist не включён, `RuntimeSettingDocument` rows отсутствуют.

Cutover заблокирован: две существующие записи имеют `service_id=s1`. Старый код
показывает этот стабильный код как «КТ головного мозга», новый — как «Амбул.
операция (офт.)». Миграция меняет только Django choices и не преобразует данные,
поэтому новый image молча изменил бы бизнес-смысл записей. Нужен явный выбор
владельца: удалить одноразовые тестовые записи после export, задать соответствие
либо сохранить legacy-код и ввести новые стабильные коды.

После schema-only окна старый контейнер не прошёл повторный startup check из-за
существующего `core.E001` по удалённому из рабочего реестра AI-инструменту.
Предыдущее поведение test-host восстановлено тем же старым image с прямым
запуском Gunicorn; `/health/` и agent-runtime `/health` успешны. Это временный
режим: до следующего штатного restart нужен новый совместимый image либо
согласованное исправление runtime registry.

## Непринятая часть

Production cutover не выполнялся и этим acceptance не разрешён. Перед ним нужны
решение по двум legacy-записям, применение `waiting_list.0006`, чистый final plan,
freeze, приватный allowlist и read-only окно наблюдения. Резервные копии и
`settings_center.0004` уже подготовлены, но сами по себе cutover не разрешают.
