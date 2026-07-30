# Workflow Brief: test-runtime-and-agent-cost-optimization

Статус: archived.

Дата: 2026-07-30.

## Цель

Реализовать единый быстрый и воспроизводимый тестовый контур для локальной разработки,
ИИ-агентов и GitHub Actions.

## Read scope

- `AGENTS.md`;
- `Makefile`, `pytest.ini`, `requirements*.txt`;
- `config/settings.py`;
- `.github/workflows/tests.yml`;
- `apps/**/tests.py`, `apps/**/tests/test_*.py`;
- `services/agent_runtime/tests/`;
- `scripts/e2e/`;
- `docs/guides/TESTING_POLICY.md`, `docs/guides/TEST_ACCELERATION.md`.

## Write scope

Совпадает с планом
`docs/planning/archive/2026/test-runtime-and-agent-cost-optimization.md`.

## Ограничения

- не использовать `git stash`, `git restore`, `git reset` или общий checkout;
- не изменять четыре пользовательских файла дерева заявок;
- временные журналы и профили писать только в `.local/`;
- не считать прогон при параллельном изменении файлов приёмочным;
- не включать xdist/parallel по умолчанию без отдельной проверки изоляции.

## Проверки

```bash
make check
make test-fast TEST_SCOPE=<targeted-scope>
make test
make contracts
npm run test:e2e -- --project=chromium --grep @smoke
make gen-struct
git diff --check
```
