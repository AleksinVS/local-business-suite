# Workflow Brief: testing-policy-and-independent-verification

Статус: implemented, awaiting owner acceptance.

Дата: 2026-05-29.

## Цель

Зафиксировать проектную политику тестирования и правило независимой проверки тестов быстрым проверочным субагентом для крупных, рискованных и многошаговых изменений.

## Read scope

- `AGENTS.md`
- `README.md`
- `Makefile`
- `pytest.ini`
- `package.json`
- `docs/guides/`
- `workflow/active/`

## Write scope

- `docs/guides/TESTING_POLICY.md`
- `docs/guides/.desc.json`
- `AGENTS.md`
- `README.md`
- `workflow/active/testing-policy-and-independent-verification/`
- `workflow/active/.desc.json`
- `PROJECT_STRUCTURE.yaml`

## Non-goals

- Не менять приложение, тестовый код, контракты AI или runtime.
- Не вводить обязательную multi-agent процедуру для каждой мелкой правки.
- Не менять CI/CD без отдельной задачи.

## Acceptance

- Есть постоянный guide с уровнями тестов, матрицей обязательных проверок и правилом независимого проверочного субагента.
- `AGENTS.md` содержит операционное правило для агентов.
- `README.md` ссылается на новую политику.
- Исполнительный workflow-блок содержит brief, план, task packet, отчет, приемку и ретроспективу.
- `.desc.json` и `PROJECT_STRUCTURE.yaml` обновлены после изменения структуры.

## Verification

```bash
make gen-struct
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
git diff --check
```
