# Task Acceptance: test-runtime-acceleration

Дата: 2026-06-03.

## Acceptance

- Команда `make test-fast` добавлена и использует штатный Django `--keepdb`.
- Выборочные тесты оформлены через `TEST_SCOPE`, полный прогон остается доступен через `make test` и `make test-fast` без scope.
- Проектная документация создана: `docs/guides/TEST_ACCELERATION.md`.
- Политика тестирования и README ссылаются на практический guide.
- Исполнительная документация создана в этом workflow-блоке.

## Verification

- `make test-fast TEST_SCOPE=apps.accounts.tests.LDAPAuthConfigTests.test_ad_group_sync_removes_only_ad_managed_missing_roles` — OK.
- `make check` — OK.
- `make contracts` — OK.
- `make gen-struct` — OK.
- `git diff --check -- . ':(exclude)BACKLOG.md'` — OK.

## Решение

Задача по ускорению повторных локальных тестов принята на уровне локальных проверок. Полный контроль покрытия остается за полным запуском тестового набора.
