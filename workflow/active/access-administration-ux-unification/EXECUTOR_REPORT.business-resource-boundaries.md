# Исполнительский отчёт: границы бизнес-ресурсов

## Объём

- Удалён неиспользуемый hard delete заявки из `apps.ai.services` и
  `apps.workorders.policies`; отмена выполняется через
  `workorders.transition` с целевым статусом `cancelled`.
- Обновлены архитектурный обзор и активный план: заявка и
  `WorkOrderTransitionLog` сохраняются после отмены.
- Добавлены проверки fail-closed для старого `PendingAction` с кодом
  `workorders.delete` и сквозной AI-проверкой отмены через переход статуса.

## Проверки

- `git diff --check` — успешно.
- `.venv/bin/python manage.py test apps.ai.tests.test_identity_context.IdentityContextPropagationTests services.agent_runtime.tests.test_normalization --keepdb` — `75 passed`.
- `.venv/bin/python manage.py validate_architecture_contracts` — успешно.

## Runtime-контракты

Изменения `contracts/ai/tools.json` и `contracts/ai/task_types.json` должны быть
перенесены в рабочие копии `data/contracts/ai/` основным агентом через штатный
протокол Settings Center (preview/apply/CAS/audit). Файлы `data/contracts/`
напрямую не изменялись.

## Ограничения

Параллельные изменения selector/read-boundary оставлены без вмешательства.

## Correction package 16 после независимого FAIL

Исправлено в заданном write scope:

- добавлен bounded `resolve_active_actor` в `apps.workorders.selectors`; публичные workorder/board/department/device selectors, inventory adapters и AI read services принудительно перечитывают активного пользователя из БД;
- HTTP dashboard/analytics/inventory/workorder boundaries используют свежий actor для видимости и управляющих флагов;
- зафиксирован порядок блокировок команд: `actor → boards(sorted) → workorder → departments(sorted) → devices → assignee`; update cross-board сначала читает IDs без авторизации, затем блокирует доски в порядке `pk` и повторяет проверки;
- assignee блокируется через `select_for_update`, повторно проверяется как active; сохранена продуктовая семантика `manage_assignments`, допускающая любого активного пользователя;
- unchecked helpers переименованы в `_create_workorder_unchecked`, `_transition_workorder_unchecked`, `_confirm_closure_unchecked`, `_rate_workorder_unchecked`; production callers остались только внутри command functions;
- добавлены проверки stale actor, revoke/deactivate, cross-board и assignee race в actor command tests; существующие тестовые вызовы обновлены на новые приватные имена.

Тесты после коррекции не запускались. Выполнены статические проверки:

```text
AST compile OK: 13 files
git diff --check: OK
```

Остаточный риск: реальная PostgreSQL-конкурентность и HTTP/AI integration matrix требуют отдельного последовательного запуска основным агентом.

## Correction package 16 после второго FAIL

- protected workorder views больше не используют fallback на stale `request.user`: при отсутствии свежего actor detail/action закрывается через 403, а board/context возвращает пустое состояние; transition/rating/column capability checks используют только свежий actor;
- `clone_board` теперь сначала блокирует actor, затем проверяет capability и только после этого блокирует source board;
- Django Admin запрещает hard delete для `WorkOrder` и `Board`, включая superuser, но сохраняет add/change резервный путь; `delete_model` и `delete_queryset` для заявок явно закрыты;
- `seed_board --clear` больше не удаляет заявки и выдаёт `CommandError`, если на доске есть workorders; пустая доска остаётся без destructive cleanup;
- production-поиск `WorkOrder` delete в `apps/workorders` не обнаружил обходов; оставшаяся migration-операция удаляет только историческую bootstrap-доску и не является runtime-командой;
- добавлены проверки admin hard-delete, fail-closed seed cleanup и clone после revoke capability.

Тесты не запускались. Статическая проверка текущей коррекции:

```text
AST compile OK: 6 files
git diff --check: OK
```

## Correction package 16 после финального FAIL

- Перед каждым HTMX-рендером после команды записи в `apps.workorders.views`
  повторно авторизуются actor и целевая заявка: комментарий, вложение,
  переход, перемещение, подтверждение закрытия, оценка и редактирование
  колонок. При отзыве активности/роли, смене области видимости или потере
  доски возвращается `403`; фрагмент не получает чужой объект, форму или
  контекст. Для досочного фрагмента отсутствие `board_columns` также является
  `403`, а не ошибкой ключа.
- Добавлен внутренний `_policy_actor`, который переиспользует только явно
  помеченный snapshot в пределах одной операции. Board render-path передаёт
  этот snapshot в selectors и policy checks; публичная граница по-прежнему
  перечитывает actor из БД.
- В `apps.workorders.selectors` разделены публичные fresh-resolve функции и
  внутренние actor-aware queryset helpers для ролей досок, заявок,
  подразделений и совместного выбора подразделений/устройств. В
  `apps.inventory.selectors` добавлены соответствующие внутренние helpers;
  `visible_devices` и creation path используют один snapshot.
- Добавлены regression HTTP-проверки для отзыва доступа перед рендером
  комментария, вложения и перемещения, а также deterministic-проверка одного
  actor lookup в публичном selector boundary.

Тесты после этой коррекции не запускались по запросу координатора. Выполнены
статические проверки:

```text
AST compile OK: 14 files
git diff --check: OK
```

Остаточный риск: реальная PostgreSQL-конкурентность clone/update и полная
HTTP/AI матрица требуют последовательного запуска основным агентом; SQLite не
позволяет достоверно подтвердить взаимное поведение транзакционных блокировок.
