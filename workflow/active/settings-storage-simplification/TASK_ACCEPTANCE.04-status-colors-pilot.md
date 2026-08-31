# Приёмка пакета 04: палитра листа ожидания

Статус: **Accepted for dev/test; production cutover pending**  
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

## Непринятая часть

Production cutover не выполнялся и этим acceptance не разрешён. Перед ним нужны
`settings_center.0004`, чистый final plan, backup/freeze, приватный allowlist,
окно наблюдения и отдельное решение владельца.
