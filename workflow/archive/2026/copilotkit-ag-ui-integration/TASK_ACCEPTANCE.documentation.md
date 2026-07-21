# Task Acceptance: documentation

Дата: 2026-06-09.

## Acceptance

- ADR-0027 создан и фиксирует proposed-решение.
- Архитектурный план описывает целевую схему, этапы, риски и проверки.
- Operations guide описывает режимы включения, smoke, troubleshooting и rollback.
- Deployment note описывает Linux/VPS и Windows/IIS контуры.
- Planning-файл создан в `docs/planning/active/`.
- Workflow-блок создан в `workflow/archive/2026/copilotkit-ag-ui-integration/`.
- Task packets покрывают documentation, AG-UI adapter, Copilot Runtime, React island, security/deployment и e2e acceptance.

## Verification

Ожидаемые проверки для документационного среза:

```bash
python manage.py validate_architecture_contracts
make gen-struct
git diff --check
```

Фактические результаты фиксируются в финальном отчете текущей ветки.

## Решение

Документационный срез считается готовым к review владельцем. Реализация должна стартовать отдельным срезом после согласования ADR и deployment-подхода.
