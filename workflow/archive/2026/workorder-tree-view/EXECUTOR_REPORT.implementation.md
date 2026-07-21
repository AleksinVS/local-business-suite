# Executor Report: implementation

Дата: 2026-05-30.

## Выполнено

- Добавлен branch-aware scope `department_branch` для заявок.
- Роль `customer` в дефолтном контракте и текущей рабочей копии переведена на `department_branch`.
- Общий валидатор контрактов и экран ролей знают новый scope.
- `visible_workorders_queryset()` фильтрует заявки по ветке `User.department`.
- Формы создания и редактирования заявок ограничивают `department` и `device` доступной веткой.
- Добавлен серверный builder дерева `apps/workorders/tree.py`.
- Страница заявок получила режимы `view=board` и `view=tree`.
- Фильтры обновляют общий контейнер текущего режима через HTMX.
- Создание, открытие и редактирование заявки из дерева используют существующий правый сайдбар.
- Добавлены partials дерева и переключателя режимов.
- Добавлены стили дерева в стиле доски и JS для раскрытия, клавиатуры и refresh после изменений.
- Добавлены unit/view тесты и e2e spec для дерева.
- Обновлены `.desc.json` и `PROJECT_STRUCTURE.yaml`.

## Проверки

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py validate_architecture_contracts
.venv/bin/python manage.py test apps.workorders.tests --keepdb
.venv/bin/python manage.py test apps.core.tests --keepdb
npm run test:e2e -- --project=chromium --grep "workorder tree"
make gen-struct
git diff --check
```

Фактический результат:

- `manage.py check` - passed.
- `validate_architecture_contracts` - passed.
- `apps.workorders.tests` - 58 tests passed.
- `apps.core.tests` - 35 tests passed.
- `workorder tree` e2e - 2 tests skipped, потому что не заданы `E2E_USERNAME` и `E2E_PASSWORD`.
- `make gen-struct` - passed.
- `git diff --check` - passed.

## Остаточные риски

- Браузерный e2e нужно выполнить на стенде с заданными `E2E_USERNAME`, `E2E_PASSWORD` и доступными заявками.
- Заказчики без заполненного `User.department` увидят пустой набор заявок.
- Если исторические заявки заказчика находятся вне его ветки, после включения `department_branch` они станут недоступны этому заказчику.
