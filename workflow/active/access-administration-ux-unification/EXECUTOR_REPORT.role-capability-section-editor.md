# Executor report: role capability section editor

## Реализовано

- Добавлена единая классификация возможностей в `apps.accounts.access_contracts`.
  Текущие workorder scope/targets и `manage_assignments` относятся к заявкам;
  специальные capability-коды распределены по разделам; будущие `manage_*`
  попадают в администрирование, неизвестные scope/targets — в области доступа,
  остальные — в прочие права.
- Read model роли и таблица разделов сайта используют одну классификацию без
  изменения role_rules и runtime-контракта.
- `RoleDefinitionForm` предоставляет `capability_groups`, связанные BoundField
  и hidden `active_group`, который сохраняется при preview/apply.
- Правый инспектор роли получил локальный групповой редактор: слева вкладки и
  компактные название/описание, справа одна активная группа прав; ссылка на
  сотрудников роли сохранена.
- Standalone редактор роли использует те же группы и локальное переключение,
  включая сохранение черновика и dirty-предупреждение.
- Добавлены unit/Django/Playwright-проверки полноты группировки, inspector и
  локального переключения.
- Добавлена общая `role_capability_editor.js` для inspector и standalone:
  локальное переключение, Arrow/Home/End навигация и корректные tab/tabpanel
  состояния.
- Исправлен standalone preview: display_name/description передаются отдельными
  initial-значениями, capability-поля — только по capability-кодам.
- В preview inspector добавлены impact hints, таблица before/after/risk,
  non-field errors и подтверждение риска; группа памяти содержит пояснение о
  раздельном назначении технических групп.

## Проверки

- `node --check static/src/js/access_workspace.js` и
  `node --check static/src/js/role_capability_editor.js` — успешно.
- `python3 -m py_compile` для изменённых Python-модулей — успешно.
- `manage.py check` — успешно, 0 ошибок.
- Прямая проверка классификатора: 20 capability, 20 сгруппированных, 20
  уникальных; текущие workorders scope/targets распределены в `workorders`.
- Проверены fallback-категории для будущих `manage_*` и scope/targets.
- Основной агент сообщил успешный целевой прогон `make verify-fast
  TEST_SCOPE=apps/settings_center/tests.py`: 74 passed + 9 subtests.
- После сброса только тестовой БД `make verify-profile PROFILE=ui`: 269 тестов,
  18 subtests и 16 Playwright smoke-сценариев успешно.
- Финальный `make verify-full`: 714 тестов и 104 subtests успешно.
- Основной агент визуально проверил правый drawer на 1440×1000 и 390×844:
  группы находятся слева на широком экране и становятся горизонтальной лентой
  на узком, активные права не перекрывают заголовок и действия.

## Остаточный риск

Остаточный риск ограничен браузерами, не входящими в Chromium smoke-профиль.
