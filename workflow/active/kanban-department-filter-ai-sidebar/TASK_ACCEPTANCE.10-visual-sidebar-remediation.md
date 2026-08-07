# Приемка пакета 10

Статус: Technically accepted; owner acceptance pending.

Функциональные критерии исправлены и подтверждены целевыми браузерными сценариями.

Проверено:

- `make verify-fast TEST_SCOPE=apps/workorders/tests.py` — 92 passed, 3 subtests passed;
- `make verify-profile PROFILE=ui` — 222 passed, 9 subtests passed и browser smoke 1 passed;
- целевой Playwright — 3 passed;
- после повторной визуальной обратной связи целевой Playwright отображения названий — 1 passed;
- `make verify-full` — 579 passed, 80 subtests passed;
- system check, migrations, staticfiles, 17 архитектурных контрактов, `jq`,
  `make gen-struct` и `git diff --check` — успешно.

Первый профильный smoke был запущен без E2E-учётных данных и остановился на странице
входа. Повтор с предусмотренной проектом демо-учётной записью прошёл. Первый полный
прогон остановился до тестов на рассинхронизации `static/src/` и `staticfiles/`; после
штатного `collectstatic` полный прогон завершился успешно.
