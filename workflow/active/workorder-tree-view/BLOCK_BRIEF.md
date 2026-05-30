# Workflow Brief: workorder-tree-view

Статус: implemented MVP, awaiting owner acceptance.

Дата: 2026-05-30.

## Цель

Добавить на страницу заявок режим сворачиваемого дерева по организации, подразделениям, отделениям, медизделиям и заявкам, сохранив текущую доску, стиль карточек и работу через правый сайдбар.

## Архитектурные источники

- `docs/adr/ADR-0023-workorder-tree-view-and-customer-branch-access.md`
- `docs/planning/active/workorder-tree-view.md`

## Read scope

- `apps/workorders/views.py`
- `apps/workorders/selectors.py`
- `apps/workorders/policies.py`
- `apps/workorders/forms.py`
- `apps/workorders/models.py`
- `apps/accounts/models.py`
- `apps/core/models.py`
- `apps/inventory/models.py`
- `templates/workorders/board.html`
- `templates/workorders/partials/`
- `static/src/css/app.css`
- `static/src/js/`
- `contracts/role_rules.json`
- `contracts/schemas/role_rules.schema.json`
- `apps/workorders/tests.py`
- `scripts/e2e/tests/`
- `docs/adr/`
- `docs/planning/active/`

## Write scope

- `apps/workorders/tree.py`
- `apps/workorders/selectors.py`
- `apps/workorders/policies.py`
- `apps/workorders/forms.py`
- `apps/workorders/views.py`
- `templates/workorders/board.html`
- `templates/workorders/partials/workorder_view_switcher.html`
- `templates/workorders/partials/tree_view.html`
- `templates/workorders/partials/tree_row.html`
- `static/src/css/app.css`
- `static/src/js/workorder_tree.js`
- `contracts/role_rules.json`
- `contracts/schemas/role_rules.schema.json`, если вводится новый enum scope
- `apps/workorders/tests.py`
- `scripts/e2e/tests/workorder_tree.spec.ts`
- `.desc.json`
- `PROJECT_STRUCTURE.yaml`
- `docs/planning/active/workorder-tree-view.md`
- `workflow/active/workorder-tree-view/`

## Non-goals

- Не создавать отдельную модель `Organization`.
- Не менять workflow статусов заявок.
- Не переделывать канбан-доску.
- Не добавлять drag-and-drop внутри дерева.
- Не добавлять batch-операции.
- Не внедрять клиентскую виртуализацию в первом срезе.

## Acceptance

- Режимы "Доска" и "Дерево" переключаются на одной странице заявок.
- Режим сохраняется в URL и не сбрасывает фильтры.
- Дерево строится только по серверно доступным заявкам.
- Заказчик видит только ветку своего `User.department`.
- Подразделения и медизделия в формах создания/редактирования ограничены доступной веткой заказчика.
- Заявка из дерева открывает существующий правый сайдбар.
- Создание из дерева открывает правый сайдбар с предзаполненным подразделением или изделием.
- Стили дерева используют текущие токены, карточки, статусы и сайдбар доски.
- Unit, view и e2e проверки проходят или остаточный риск зафиксирован.

## Verification

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.workorders.tests
E2E_BASE_URL=http://127.0.0.1:8000 E2E_USERNAME=chief_manager E2E_PASSWORD=... npm run test:e2e -- --project=chromium --grep "workorder tree"
make gen-struct
git diff --check
```
