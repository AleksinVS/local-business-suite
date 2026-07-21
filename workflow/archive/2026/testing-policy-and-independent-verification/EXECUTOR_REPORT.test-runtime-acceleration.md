# Executor Report: test-runtime-acceleration

Дата: 2026-06-03.

## Сделано

- В `Makefile` добавлен `test-fast`, который запускает Django-тесты с `--keepdb`.
- Добавлены параметры `TEST_SCOPE` и `TEST_FLAGS` для выборочного scope и дополнительных флагов test runner.
- В `docs/guides/TESTING_POLICY.md` добавлено правило использования `test-fast` и `TEST_SCOPE`.
- Создан `docs/guides/TEST_ACCELERATION.md` с практическими способами ускорения тестов без снижения покрытия.
- Обновлена навигация в `README.md` и `docs/guides/.desc.json`.
- Добавлен task packet `02-test-runtime-acceleration.json`.

## Проверки

- `make test-fast TEST_SCOPE=apps.accounts.tests.LDAPAuthConfigTests.test_ad_group_sync_removes_only_ad_managed_missing_roles` — OK, 1 test, использована существующая тестовая база.
- `make check` — OK.
- `make contracts` — OK.
- `make gen-struct` — OK.
- `git diff --check -- . ':(exclude)BACKLOG.md'` — OK.

## Остаточные риски

- `--parallel auto` не включен по умолчанию: сначала нужно отдельно проверить совместимость со всеми database aliases.
- Выборочный `TEST_SCOPE` ускоряет локальную обратную связь, но не заменяет полный прогон перед приемкой крупной или рискованной работы.
- `pwsh` недоступен в текущей Linux-среде, поэтому Windows PowerShell-скрипты проверяются документационно и через Django-проверки, не parser-прогоном PowerShell.
