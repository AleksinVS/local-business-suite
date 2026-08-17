# Executor report: делегированное редактирование определений ролей

## Реализовано

- В `apps.accounts.access_contracts` добавлен единый predicate
  `can_edit_role_definitions`: допускаются только активные аутентифицированные
  superuser, `is_staff` или участник контрактной роли `admin`.
- Predicate проведён через Access Workspace, standalone RoleDefinition,
  right-inspector и `_require_contract_editor` для `core.contract.role_rules`.
  Менеджер с одним `manage_roles` сохраняет read-only доступ к карточке роли,
  но не получает форму редактора и не проходит service guard.
- В подписанное actor state добавлен `is_staff`; смена этого флага инвалидирует
  preview/apply вместе со статусом, superuser-флагом и составом ролей.
- При недоступном или повреждённом role contract predicate возвращает отказ
  (fail-closed), не раскрывая административный доступ по старому состоянию.
- Навигация «Доступ» показывается staff/admin-role actor, при этом существующий
  доступ менеджера к рабочему окну назначения не убран.
- Добавлен интеграционный тест клика по имени роли без `field`, матрица
  superuser/staff/admin-role/manager-only/regular/inactive и прямые проверки
  service guard.

## Документация

Обновлены ADR-0040, руководство пользователя, deployment-инструкция и активный
план. Git-дефолт `contracts/ai/tools.json` синхронизирован с Python-реестром.
Рабочая копия `data/contracts/ai/tools.json` обновлена штатным атомарным сервисом
Settings Center; создан `SettingsChange #9` со статусом `applied`.

## Проверки

- `manage.py check` — успешно.
- Узкий тест матрицы допуска и клика по роли: `1 passed, 6 subtests,
  75 deselected` за 2.90 секунды.
- В той же матрице проверена инвалидация preview после снятия `is_staff` у
  actor, который сохраняет роль `admin`.
- Регрессия существующего role preview/service набора: `4 passed, 72 deselected`
  за 2.43 секунды.
- `./.venv/bin/python manage.py check` — успешно, `py_compile` затронутых
  модулей — успешно, `git diff --check` — успешно.
- Settings Center узкие проверки: `3 passed, 74 deselected` за 1.72 секунды.
- Core legacy redirect/navigation: `3 passed, 5 subtests, 86 deselected` за
  1.64 секунды.
- AI metadata и prepare/service matrix: `2 passed, 2 subtests, 75 deselected`
  за 1.10 секунды.
- В correction cycle обновлены старые staff/manager и legacy-route тесты,
  добавлена проверка fail-closed при `ContractStoreError`, а AI prepare matrix
  подтверждает доступ staff/admin-role и отказ manager-only.
- Исправлен отдельный legacy-route тест: manager получает 403, inactive actor —
  302 из-за отказа восстановления сессии; проверка: `1 passed, 2 subtests,
  88 deselected` за 1.44 секунды.
- `git diff --check` — успешно. Git-дефолт и runtime-копия инструмента
  синхронизированы с `role_definition_editor`.

## Сквозная e2e-команда

`access_administration_e2e` теперь клонирует конфигурации `technician` и
`manager` во временные контрактные роли `__access_admin_e2e_technician__` и
`__access_admin_e2e_manager__`. Для member/control и board ACL используются
только одноимённые временные Group; рабочие группы `technician` и `manager`
больше не участвуют в сценарии. Поэтому impact остаётся
`role_member_count=2`, `effective_change_count=1`,
`unchanged_by_other_role_count=1` независимо от реальных участников обеих
live-ролей. Исходные роли и их membership не изменяются; временные роли,
группы, пользователи, доска и аудиты удаляются.

Регрессионная проверка создаёт посторонних участников в обеих live-группах и
подтверждает сохранение их членства после выполнения команды. Узкие тесты:
`2 passed, 76 deselected` за 4.06 секунды. Сквозной запуск на заполненной
PostgreSQL-базе: `access_administration_e2e: OK`, временные данные удалены.
- `git diff --check` — успешно.

## Остаточный риск

Финальная объединённая проверка: `239 passed`, `5 deselected`, `36 subtests`.
`manage.py check` и `validate_architecture_contracts` в контейнере успешны.
Три Playwright-сценария правого редактора роли прошли в Chromium: локальное
переключение групп с сохранением черновика, единая группа прав канбана и
серверный preview с impact/diff без перезагрузки страницы. Временный
суперпользователь и созданная им сессия чата удалены.

Кнопки создания новой контрактной роли пока нет; руководство явно направляет
для доступа к листу ожидания на существующую роль «Врач». Поддерживаемое
создание отдельной роли остаётся самостоятельным продуктовым срезом.
