# Block brief: test-workflow-simplification-2026-08-06

Статус: active.

## Цель

Упростить тестовый workflow до трех уровней, устранить зависимость от локальных
артефактов и сохранить полный контроль качества в CI и при приемке.

## Read scope

`AGENTS.md`, `README.md`, `Makefile`, `pytest.ini`, `config/settings_test.py`,
`.github/workflows/tests.yml`, `docs/guides/TEST*.md`, `apps/**/tests*`,
`services/agent_runtime/tests/`, `scripts/e2e/`.

## Write scope

Совпадает с активным планом
`docs/planning/active/test-workflow-simplification-2026-08-06.md`.

## Проверки

- `make check`;
- `make verify-fast TEST_SCOPE=<target>`;
- `make verify-profile PROFILE=<profile>`;
- `make verify-full`;
- `npm run test:e2e:smoke`;
- разбор YAML/JSON и `git diff --check`.
