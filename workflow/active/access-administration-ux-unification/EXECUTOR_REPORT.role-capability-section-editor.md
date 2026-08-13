# Executor report: role capability section editor

## Реализовано

- Добавлена единая классификация возможностей в `apps.accounts.access_contracts`.
  Текущая явная карта распределяет все права канбан-доски, включая доски и
  назначения, в одну группу; остальные capability-коды распределены по
  пользовательским разделам, а неизвестные runtime-права — в прочие права.
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

## Исправление таксономии (пакет 12)

Классификация переведена на явную карту `CAPABILITY_GROUP_BY_CAPABILITY` в
`apps/accounts/access_contracts.py`. В ней ровно все текущие права из
`capability_catalog()` (20 кодов), каждое ровно один раз:

- `kanban`: `view_scope`, `create_workorder`, `edit_scope`, `comment_scope`,
  `upload_attachment_scope`, `manage_assignments`, `transition_scope`,
  `transition_targets`, `confirm_closure_scope`, `rate_scope`,
  `manage_board_columns`;
- `inventory`: `manage_inventory`;
- `waiting_list`: `view_waiting_list`, `create_waiting_list`;
- `analytics`: `view_analytics`;
- `departments`: `manage_departments`;
- `access`: `manage_roles`;
- `ai`: `manage_ai_skills`;
- `memory`: `memory_organization_write`, `memory_organization_review`.

Группы получили пользовательские названия «Канбан-доска», «Медизделия»,
«Лист ожидания», «Аналитика», «Подразделения», «Доступ», «ИИ-центр», «Память
организации» и «Прочие права». Эвристики по `manage_*`, `scope/targets` и
старому `metadata.section` удалены; неизвестное runtime-право попадает в
`other`, а в тесте custom catalog проверяется, что оно не теряется и создаёт
ровно одну дополнительную группу. Базовый активный пользователь без роли теперь
относится к «Канбан-доске». Обновлены unit/Django/e2e проверки, руководство и
активный план.

Для пакета 12 выполнены `make verify-fast
TEST_SCOPE=apps/settings_center/tests.py` (74 теста и 9 подслучаев) и, после
сброса только загрязнённой тестовой БД, `make verify-profile PROFILE=ui`
(269 тестов, 18 подслучаев и 17 браузерных сценариев). Браузерный сценарий
проверяет, что у роли администратора видна одна вкладка «Канбан-доска», все
одиннадцать прав находятся в одной видимой панели, а старые технические вкладки
отсутствуют. Основной агент визуально проверил интерфейс на 1440×1000 и 390×844.
