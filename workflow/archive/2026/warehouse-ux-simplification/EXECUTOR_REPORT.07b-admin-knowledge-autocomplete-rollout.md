# Executor report: 07b — автодополнение административных и knowledge-модулей

## Выполнено

Проверены пользовательские формы `accounts`, `settings_center`, `filehub`,
`memory`, `analytics` и `ai`. Резервный Django Admin в rollout не включался.

- Добавлены доменные поставщики общего транспорта:
  `accounts.department`, `accounts.role_principal`, `memory.source`,
  `memory.issue_assignee`, `filehub.file_object`.
- Подразделение пользователя переведено на entity-autocomplete в основной
  рабочей области доступа, общем редакторе пользователя и резервных
  пользовательских формах Settings Center. Provider доступен только активному
  superuser; серверная `ModelChoiceField` по-прежнему проверяет
  `available_user_departments()` и не принимает карантинное подразделение.
- Редактор участников роли больше не рендерит полный список пользователей.
  Текущие управляемые участники показаны removable chips, новый участник
  добавляется одиночным entity-picker с контекстом роли. Текущие назначения
  вне privilege ceiling сохраняются скрытыми. Поддельный `selected_user_ids`,
  `new_user_id` или `remove_user_id`, отключённая учётная запись и назначение
  защищённой роли отклоняются до записи. Канонический подписанный
  preview/apply-сервис и аудит состава роли не менялись.
- В FileHub выбор файла переведён с первых 200 `<option>` на bounded provider
  поверх `file_object_autocomplete_candidates`: база сначала ограничивает
  кандидатов по `file_id`, коду источника или безопасному `file_name`, затем к
  окну не более 100 записей применяется канонический ACL и возвращается не
  более 20 результатов. Ответ содержит только имя файла и код источника, без
  physical/raw path. POST повторно применяет
  `can_access_file_object`; сохранение остаётся в существующем
  `save_user_virtual_placement`.
- В Memory review фильтры источника для issue/index и назначение эксперта
  используют общий компонент. Источники берутся только из
  `source_filter_options`; issue заново разрешается через
  `review_issue_queryset`. До поиска principals provider требует наличие
  действия `assign` в каноническом `issue_available_actions`, поэтому
  `memory_observer` не может перечислять экспертов. Кандидаты экспертов сначала
  ограничиваются запросом и окном базы, затем проходят `assignees_for_issue`.
- Матрица `docs/guides/PORTAL_AUTOCOMPLETE_FIELD_MATRIX.md` обновлена до
  окончательных статусов 07b. Каталоги ролей пользователя и технических групп
  памяти оставлены компактными contract-backed multi-select: полный видимый
  набор нужен для безопасного сравнения, а сами каталоги не растут из
  пользовательских данных.
- В Analytics пользовательский UI только читает агрегаты. В AI модель и
  команды выбираются из ограниченных реестров; prompt/title/file относятся к
  специализированным полям. Новые providers там не создавались. AG-UI wire,
  версии и зависимости не менялись.
- Обновлены `.desc.json` и сгенерирован `PROJECT_STRUCTURE.yaml`. Settings
  Center repository и его путь записи не менялись.

## Проверки

После последних функциональных правок выполнены:

- `LOCAL_BUSINESS_SQLITE_PATH=.local/07b-final-focused.sqlite3 python manage.py test apps.settings_center.tests.AccessAutocompleteSecurityTests apps.settings_center.tests.AccessWorkspaceTests.test_inline_role_membership_uses_bulk_save_and_audits_target apps.settings_center.tests.AccessWorkspaceTests.test_role_membership_editor_uses_bounded_add_picker_and_removable_members apps.settings_center.tests.AccessWorkspaceTests.test_role_membership_picker_rejects_forged_inactive_principal apps.memory.tests.test_admin_and_review_ui.MemoryReviewUITests.test_memory_autocomplete_requires_review_access_and_renders_shared_widgets apps.filehub.tests.FileObjectAutocompleteSecurityTests --verbosity 1` — **9 tests, OK**.
- `LOCAL_BUSINESS_SQLITE_PATH=.local/07b-account-services.sqlite3 python manage.py test apps.accounts.tests.AccessAssignmentServiceTests apps.settings_center.tests.AccessCommentPolicyTests --verbosity 1` — **37 tests, OK**, включая `access_management_e2e`.
- `LOCAL_BUSINESS_SQLITE_PATH=.local/07b-memory-ui.sqlite3 python manage.py test apps.memory.tests.test_admin_and_review_ui.MemoryReviewUITests apps.filehub.tests.FileObjectAutocompleteSecurityTests --verbosity 1` — **12 tests, OK**.
- После независимого review:
  `LOCAL_BUSINESS_SQLITE_PATH=.local/07b-corrections.sqlite3 python manage.py test apps.memory.tests.test_admin_and_review_ui.MemoryReviewUITests.test_memory_autocomplete_requires_review_access_and_renders_shared_widgets apps.memory.tests.test_admin_and_review_ui.MemoryReviewUITests.test_memory_observer_cannot_enumerate_issue_assignees apps.filehub.tests.FileObjectAutocompleteSecurityTests --verbosity 1` — **4 tests, OK**.
- `python manage.py check` — успешно; осталось штатное предупреждение
  `settings_center.W002` о состоянии миграции документов настроек.
- `node scripts/dev/generate-structure.js` — успешно.

Расширенный промежуточный запуск 94 тестов не использован как критерий 07b:
он выполнялся во время параллельных изменений общего role/capability contract и
получил 13 падений в старых тестах определения ролей. Все целевые тесты 07b и
канонический сервис назначения ролей затем выполнены отдельно и прошли.

## Остаточные риски

- Сквозной браузерный сценарий с клавиатурой для новых administrative/memory
  полей не запускался; основной компонент уже покрывается общим e2e пакета 01,
  а здесь выполнены HTTP, шаблонные и security-проверки.
- Поставщики участников роли, экспертов памяти и файлов намеренно просматривают ограниченное число
  подходящих кандидатов за запрос. При очень крупном каталоге пользователей
  или файлов оператор должен вводить часть имени, логина или безопасного имени
  файла; полный список никогда не отдаётся. Окно кандидатов ограничено 100,
  итоговый ответ — 20 элементами.
- Физические пути FileHub не выдаются provider-ом, но безопасное имя файла и
  код уже доступного источника видимы авторизованному пользователю как и в
  существующей странице размещений.
