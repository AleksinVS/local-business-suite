# Отчет исполнения 01-test-workflow-simplification

Статус: accepted.

Дата: 2026-08-06.

## Реализовано

- тестовый `STATIC_ROOT` вынесен в `.local/test-staticfiles`;
- добавлен безопасный `make test-db-reset`;
- добавлены `verify-fast`, профили `ai/memory/ui/contracts/deployment` и
  `verify-full`;
- `test-parallel` разделяет `not serial` workers и последовательный `serial`;
- добавлен pytest-плагин единственного основного маркера `unit/integration`;
- классифицированы memory, core, waiting list, workorders и agent runtime;
- CI переведен на Make-цели и fail-safe анализ измененных путей;
- добавлен самодостаточный `scripts/e2e/run-smoke.sh` и настоящий
  авторизованный браузерный smoke;
- обновлены AGENTS, README и постоянные руководства по тестированию.

## Проверки

- pytest collection: 557 тестов, все классифицированы;
- `make test-unit`: 113 passed, 4 subtests, 6.07 s;
- `make verify-fast TEST_SCOPE=apps/ai/tests/test_views.py`: passed;
- marker policy: 2 passed;
- contracts profile: 48 passed, 61 deselected;
- deployment profile: 29 passed, 8 subtests;
- memory profile: 90 passed, 59 subtests;
- parallel split: 2 non-serial passed в 2 workers, затем 11 serial и 4 subtests passed;
- browser smoke через общий script: 1 passed, 6.3 s Playwright;
- `make verify-full`: 557 passed, 75 subtests, 130.60 s;
- YAML/JSON parsed successfully; `git diff --check` passed.

## Диагностика

Первый пробный параллельный запуск обнаружил отсутствие опции
`--no-error-for-empty` в pytest 9. Цель исправлена: код 5 допускается только для
пустой части; любой другой код остается ошибкой. После изменения разделенный
сценарий прошел.

## Документация

Обновлены `AGENTS.md`, `README.md`, `docs/guides/TESTING_POLICY.md` и
`docs/guides/TEST_ACCELERATION.md`. ADR не создавался, так как production
runtime, contracts и security/privacy model не менялись.

## Остаточный риск

Чистый полный прогон в текущем окружении занял 130.60 секунды против
исторического baseline 67.94 секунды. Корректность подтверждена; отдельное
профилирование полного прогона не повторялось, чтобы не нарушать правило одного
полного приемочного запуска. Параллельный режим остается дополнительным, а не
приемочным барьером.
