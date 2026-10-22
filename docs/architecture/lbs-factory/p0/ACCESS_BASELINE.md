# Независимая инвентаризация ACCESS-00 / BM-00

Статический исходный отчёт P0; общий статус и результаты запусков — в
[проверках](VERIFICATION.md), навигация — [P0](../13_P0_BASELINE.md).


## Оглавление

- [1. Граф зависимостей и границы](#1-граф-зависимостей-и-границы)
- [2. Семантика, которую нужно сохранить при ACCESS-01](#2-семантика-которую-нужно-сохранить-при-access-01)
- [3. Источник role document и обратимость](#3-источник-role-document-и-обратимость)
- [4. Исходный каталог и grants (Git defaults, НЕ рабочая БД)](#4-исходный-каталог-и-grants-git-defaults-не-рабочая-бд)
- [5. Матрица отрицательных случаев и существующие проверки](#5-матрица-отрицательных-случаев-и-существующие-проверки)
- [6. Пробелы и границы готовности](#6-пробелы-и-границы-готовности)
- [7. Полный индекс прямых текстовых обращений к role resolver/document](#7-полный-индекс-прямых-текстовых-обращений-к-role-resolverdocument)

Дата: 2026-10-22. Снимок исходников: `2c250ae30e496434e479043ad9db84c758bce0ba`.
Режим: статическое чтение кода и тестов. Тесты, миграции и команды приложения не запускались. Фактические настройки хоста, содержимое БД, права production и производительность production не проверены. Персональные данные и значения host settings не собирались.
Исходное состояние `git status --short`: только существующий незарегистрированный файл в `drafts/`; его содержимое не читалось и не менялось.

## 1. Граф зависимостей и границы

| Откуда | Куда | Подтверждение |
|---|---|---|
| Accounts services | WorkOrders policy `can_manage_roles` | `apps/accounts/services.py:21` |
| Accounts access editor | WorkOrders `active_role_rules`, legacy viewer constants, capability value resolver | `apps/accounts/access_contracts.py:23`, `:239`, `:322`, `:974` (часть lazy imports) |
| Accounts autocomplete | WorkOrders policy и active-actor selector | `apps/accounts/autocomplete.py:13` |
| Accounts role document | WorkOrders role validator + workflow cross-document | `apps/accounts/config_documents.py:2`, `:30` |
| Core contract store | WorkOrders contracts, Waiting List validator | `apps/core/contract_store.py:30`, `:35` |
| Core views/context/forms/autocomplete | WorkOrders models/selectors/policies; Warehouse; Waiting List | `apps/core/views.py:9`, `:18`, `:20`; `apps/core/context_processors.py:3`, `:16`, `:17`; `apps/core/forms.py:7`, `:29`; `apps/core/autocomplete.py:204`, `:216` |
| Warehouse policy | Accounts quarantine helper, Core Department, WorkOrders role resolver и org branch helper | `apps/warehouse/policies.py:9`–`:12` |
| Waiting List | WorkOrders role resolver и role document | `apps/waiting_list/services.py:7`; `apps/waiting_list/policies.py:1`; `apps/waiting_list/selectors.py:5` |
| AI | WorkOrders role document, direct role reading in skill authoring | `apps/ai/services.py:13`, `:531`; `apps/ai/skill_authoring.py:33` |
| Memory | Core role store; собственный active actor и role/group tokens | `apps/memory/policies.py:94`, `:116`, `:132`, `:488` |
| Settings registry | Жёсткий список модулей descriptors/specs | `apps/settings_center/registry.py:45`; `apps/settings_center/document_registry.py:13` |
| Django bootstrap | Все три домена установлены напрямую; маршруты доступны без общего module-enabled gate | `config/settings.py:93`, `:94`, `:101`; `config/urls.py:29`, `:35`, `:36` |

`AppConfig.ready` уже даёт переходные точки регистрации: WorkOrders регистрирует AI skills, autocomplete, right panel, source adapter, media policy (`apps/workorders/apps.py:8`); Waiting List — skills/right panel/source adapter (`apps/waiting_list/apps.py:9`); Warehouse — autocomplete/right panel (`apps/warehouse/apps.py:9`). Это существующие реестры, но они не составляют общий manifest/availability/enabled/authorization lifecycle.

### Связи моделей

- `accounts.User` наследует `AbstractUser` (включая `groups`/`user_permissions`), Department — обязательный FK `PROTECT` (`apps/accounts/models.py:7`, `:12`); `GroupProfile.group` — OneToOne `CASCADE` (`:63`); audit.actor/target — `PROTECT` (`:105`, `:113`); ExternalIdentity.user — `CASCADE` (`:170`).
- `core.Department.parent` — self FK `PROTECT` (`apps/core/models.py:6`).
- `workorders.Board.allowed_groups` — M2M Django Group (`apps/workorders/models.py:40`); KanbanColumnConfig.board — `CASCADE` (`:117`); WorkOrder.board — обязательный FK `CASCADE` (`:142`). Department/author/assignee/device — `PROTECT` (`:151`, `:177`, `:183`, `:191`); assignee/device допускают отсутствие. Комментарии/attachments/transitions удаляются каскадом с WorkOrder; ссылки на авторов защищены. Запрет hard-delete в UI/admin не убирает сам риск CASCADE в схеме.
- WaitingListEntry.author — nullable `PROTECT` (`apps/waiting_list/models.py:36`); audit.entry — `CASCADE`, audit.actor — `PROTECT` (`:93`, `:99`). Прямых FK к WorkOrders/Board нет.
- Warehouse.department, StockDocument.department/created_by/posted_by и StockEntry/StockBalance org/location/item dimensions — `PROTECT` (`apps/warehouse/models.py:118`, `:280`, `:297`, `:303`, `:570`, `:676`). StockDocumentLine.document — `CASCADE` (`:401`), posted StockEntry.document/line — `PROTECT` (`:571`, `:577`); reverses_document — OneToOne `PROTECT` (`:326`). Warehouse.default_receiving_location — `SET_NULL` (`:127`). WarehouseAuditEvent.actor — `SET_NULL` (`:774`).

### Миграции

- Есть исторический цикл графа приложений Accounts ↔ Core, разрешаемый конкретным порядком миграций: Accounts 0001 зависит от Core 0003, Core 0004 — от Accounts 0003, Accounts 0008 — от Core 0006. Нельзя судить о снимаемости приложений только по текущим runtime imports (`apps/accounts/migrations/0001_initial.py:14`; `apps/core/migrations/0004_delete_organizationalunit.py:8`; `apps/accounts/migrations/0008_mandatory_user_department.py:44`).
- WorkOrders 0001 зависит от Inventory и AUTH_USER_MODEL; 0004 — Core 0001; 0014 — Core 0005; 0015 — auth/user (`apps/workorders/migrations/0001_initial.py:12`, `0004_department_reference.py:37`, `0014_alter_workorder_resolved_at_alter_workorder_status_and_more.py:9`, `0015_alter_kanbancolumnconfig_wip_limit_and_more.py:10`). Board создан/заполнен в 0009/0010 и сделан обязательным в 0011.
- Warehouse 0001 зависит от Core 0006 и AUTH_USER_MODEL (`apps/warehouse/migrations/0001_initial.py:13`); Waiting List 0001/0003/0004 — AUTH_USER_MODEL. В просмотренных миграциях Warehouse и Waiting List прямой зависимости на WorkOrders нет. Это не означает готовности к uninstall: остаются Core/Accounts/bootstrap imports.

## 2. Семантика, которую нужно сохранить при ACCESS-01

1. `active_role_rules` (`apps/workorders/policies.py:136`) возвращает `[]` для unauthenticated/inactive. Активный superuser получает один синтетический целый grant `name=superuser`. Остальным возвращаются отдельные dict каждой совпавшей контрактной роли. Без совпадений — `[]`; скрытого viewer нет (`:152`). Порядок ролей не гарантируется, поскольку user_roles возвращает set.
2. Resolver сам не перечитывает User из БД. Свежесть обеспечивают сервисные/selector boundaries. Нельзя объявлять низкоуровневый resolver защитой от stale User. Не менять молча это поведение при переносе; отдельно покрыть границы.
3. `has_role_capability` проверяет truthiness (`:232`), тогда как Waiting List create и Warehouse catalog требуют `is True` (`apps/waiting_list/policies.py:71`; `apps/warehouse/policies.py:165`). Валидатор отклоняет string flags. При переносе не менять truthiness/strict bool неявно.
4. Superuser получает все флаги каталога; scope default = all, только если допустим all, иначе none; targets = '*', только если допустима '*', иначе [] (`apps/workorders/policies.py:158`, `:211`). Новая capability не выдаётся обычной роли автоматически; у superuser автоподстановка является текущей намеренной семантикой.
5. WorkOrders transition: активность → согласованный snapshot role+workflow → видимость → глобальный граф → особая closure policy или targets+scope ОДНОЙ роли (`apps/workorders/policies.py:420`). Нельзя отдельно объединить scope и targets из разных grants. Низкоуровневый can_view не включает Board ACL; публичный queryset включает board ACL (`apps/workorders/selectors.py:124`).
6. Waiting List: явный view scope none/authored/all; при отсутствии ключа legacy view_waiting_list=True даёт all (`apps/waiting_list/selectors.py:10`). Отсутствие explicit edit/transition scope включает legacy grant: view flag=True → authored + '*' statuses, superuser → all; ЯВНОЕ none не заменяется fallback (`apps/waiting_list/policies.py:33`). Видимость может приходить из любого grant, но edit scope+statuses и transition scope+from_statuses+targets проверяются в пределах ОДНОГО grant (`:78`, `:90`). Глобальный граф ограничивает даже superuser.
7. Warehouse scopes объединяются по одной capability отдельно: own_department исключает детей, department_branch включает потомков, all = None; неизвестный capability → пустое множество. Свежий non-superuser без полноценного Department/quarantine закрыт даже при all grant (`apps/warehouse/policies.py:62`, `:82`). all view не повышает operate.
8. WorkOrders public selectors принудительно получают свежего активного actor и prefetch groups (`apps/workorders/selectors.py:34`, `:57`); Warehouse policy перечитывает actor на каждом верхнем вызове (`apps/warehouse/policies.py:36`); Waiting List write services — select_for_update actor и entry (`apps/waiting_list/services.py:70`, `:166`, `:251`). Waiting List read selector сам НЕ перечитывает actor (`apps/waiting_list/selectors.py:19`), это отдельная проверяемая граница.
9. Accounts роли и технические группы различаются по наличию в контракте, а не по префиксу имени (`apps/accounts/selectors.py:77`, `:127`). Назначение ролей сохраняет технические группы. В Memory role/group scope tokens различаются по этому же каталогу (`apps/memory/policies.py:132`).
10. Protected role: явное protected=True ИЛИ эффективная protected capability; неправильные типы, неизвестные значения и отсутствующие заявленные значения закрывают редактирование. Отсутствующая в legacy catalog новая capability не делает все старые роли защищёнными (`apps/accounts/access_contracts.py:192`). Protected capabilities перечислены в `:37`–`:52`.
11. Несуперпользователь с manage_roles может менять только обычные чужие роли; собственное назначение запрещено. Изменение protected роли (включая снятие) — только активный superuser (`apps/accounts/services.py:1053`). Редактировать собственное определение роли несуперпользователь не может; защищённость проверяется до И после (`apps/accounts/access_contracts.py:1095`). Роль viewer заморожена даже для обычного superuser editor; только dedicated migration service.
12. Preview привязан к actor/target/selection/flags/role hash+revision; apply повторно блокирует actor и target, читает fresh contract и проверяет актуальное состояние (`apps/accounts/services.py:861`–`:921`). Технические флаги меняет только свежий активный superuser. Нельзя снять собственный superuser, снять последнего активного superuser, отключить себя/последнего superuser; is_superuser требует is_staff (`:1122`, `:1432`).
13. `$defaults.new_user_role` сейчас null в Git default. Роль новым пользователям назначается только при явно настроенном валидном role code и существующей группе; создаётся audit в той же транзакции (`apps/accounts/selectors.py:90`; `apps/accounts/services.py:1198`). Уже существующему roleless пользователю viewer автоматически не выдаётся.

## 3. Источник role document и обратимость

`core.contract.role_rules`: domain/owner Accounts, database_override, Git default contracts/role_rules.json, legacy setting LOCAL_BUSINESS_ROLE_RULES_FILE, fail_closed, requires_domain_workflow, restricted; cross-validation с core.contract.workflow_rules (`apps/accounts/config_documents.py:16`). Нельзя выводить фактический backend только из storage_policy: runtime DB backend включается приватной allowlist и только для полного connected validation scope (`apps/settings_center/document_registry.py:173`–`:196`). Git settings default allowlist не подтверждает конфигурацию production. Свежий reader backend-aware (`apps/accounts/services.py:1006`).

Существующие explicit-viewer / role-administration migration / rollback commands: `apps/accounts/management/commands/{report_roleless_users,apply_roleless_user_manifest,cutover_explicit_viewer,rollback_explicit_viewer,migrate_role_administration}.py`. Полная DB/table/audit backup и проверка восстановления вне read-only аудита не выполнены; это обязательный отдельный pre-migration gate.

## 4. Исходный каталог и grants (Git defaults, НЕ рабочая БД)

Всего 32 capabilities: 13 flag, 15 scope, 4 targets; 9 контрактных ролей. Ниже полная матрица исходных значений. `false`, `none`, `[]` означают закрытое значение, а `—` отсутствие ключа (потребитель может иметь legacy fallback).

| Capability / type | viewer | customer | technician | manager | admin | doctor | warehouse_operator | warehouse_controller | warehouse_administrator |
|---|---|---|---|---|---|---|---|---|---|
| `view_scope` (scope) | `"department_branch"` | `"department_branch"` | `"assigned_or_unassigned_or_authored"` | `"all"` | `"all"` | `"none"` | `"none"` | `"none"` | `"none"` |
| `create_workorder` (flag) | `false` | `true` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `edit_scope` (scope) | `"none"` | `"authored"` | `"none"` | `"all"` | `"all"` | `"none"` | `"none"` | `"none"` | `"none"` |
| `comment_scope` (scope) | `"none"` | `"visible"` | `"visible"` | `"visible"` | `"visible"` | `"none"` | `"none"` | `"none"` | `"none"` |
| `upload_attachment_scope` (scope) | `"none"` | `"authored"` | `"visible"` | `"visible"` | `"visible"` | `"none"` | `"none"` | `"none"` | `"none"` |
| `confirm_closure_scope` (scope) | `"none"` | `"authored"` | `"none"` | `"all"` | `"all"` | `"none"` | `"none"` | `"none"` | `"none"` |
| `rate_scope` (scope) | `"none"` | `"authored"` | `"none"` | `"all"` | `"all"` | `"none"` | `"none"` | `"none"` | `"none"` |
| `transition_scope` (scope) | `"none"` | `"authored"` | `"assigned_or_unassigned_or_authored"` | `"all"` | `"all"` | `"none"` | `"none"` | `"none"` | `"none"` |
| `transition_targets` (targets) | `[]` | `["cancelled"]` | `["accepted","in_progress","on_hold","resolved"]` | `"*"` | `"*"` | `[]` | `[]` | `[]` | `[]` |
| `manage_inventory` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `manage_board_columns` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `manage_assignments` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `view_analytics` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `manage_departments` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `manage_roles` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `manage_settings` (flag) | `false` | `false` | `false` | `false` | `true` | `false` | `false` | `false` | `false` |
| `manage_ai_skills` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `memory_organization_write` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `memory_organization_review` (flag) | `false` | `false` | `false` | `true` | `true` | `false` | `false` | `false` | `false` |
| `create_waiting_list` (flag) | `false` | `false` | `false` | `false` | `false` | `true` | `false` | `false` | `false` |
| `waiting_list_view_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"all"` | `"none"` | `"none"` | `"none"` |
| `waiting_list_edit_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"authored"` | `"none"` | `"none"` | `"none"` |
| `waiting_list_edit_statuses` (targets) | `[]` | `[]` | `[]` | `[]` | `[]` | `["waiting","scheduled"]` | `[]` | `[]` | `[]` |
| `waiting_list_transition_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"authored"` | `"none"` | `"none"` | `"none"` |
| `waiting_list_transition_from_statuses` (targets) | `[]` | `[]` | `[]` | `[]` | `[]` | `["waiting","scheduled","confirmed"]` | `[]` | `[]` | `[]` |
| `waiting_list_transition_targets` (targets) | `[]` | `[]` | `[]` | `[]` | `[]` | `["waiting","scheduled","confirmed","cancelled"]` | `[]` | `[]` | `[]` |
| `warehouse_view_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"department_branch"` | `"department_branch"` | `"all"` |
| `warehouse_operate_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"department_branch"` | `"department_branch"` | `"none"` |
| `warehouse_adjust_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"department_branch"` | `"none"` |
| `warehouse_manage_locations_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"department_branch"` | `"all"` |
| `warehouse_manage_report_profiles_scope` (scope) | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"none"` | `"department_branch"` | `"all"` |
| `warehouse_manage_catalog` (flag) | `false` | `false` | `false` | `false` | `false` | `false` | `false` | `false` | `true` |

Явная protected metadata: viewer=False, customer=False, technician=False, manager=True, admin=True, doctor=True, warehouse_operator=False, warehouse_controller=True, warehouse_administrator=True. Это не подмена role_is_protected (effective semantics).

## 5. Матрица отрицательных случаев и существующие проверки

Проверки ниже обнаружены и прочитаны статически; их успешное выполнение данным аудитом не заявляется.

| Сценарий | Существующий тест (полный путь) | Зафиксированный ожидаемый исход |
|---|---|---|
| Roleless, inactive, superuser | `apps/workorders/tests.py:571` WorkOrderRoleMatrixTests.test_user_without_role_has_no_workorder_access; `:2634` CapabilityRegistryTests.test_inactive_superuser_has_no_capabilities | Пустые grants/deny, без fallback viewer |
| Явная роль без прав канбана | `apps/workorders/tests.py:990` WorkOrderViewPermissionTests.test_explicit_role_without_workorder_rights_cannot_open_board | Нет доступа к доске |
| Прямой board аргумент | `apps/workorders/tests.py:921` WorkOrderViewPermissionTests.test_selector_board_argument_cannot_bypass_board_acl | Чужая доска не раскрывает строки |
| Чужая ветка/карантин | `apps/workorders/tests.py:1076`, `:1104`; `apps/warehouse/tests/test_access.py:241`, `:305` | Ветка ограничивает чтение; карантин не расширяет до all |
| Warehouse staff-only/inactive/unknown capability | `apps/warehouse/tests/test_access.py:208` WarehouseAccessPolicyTests.test_roleless_staff_existing_role_inactive_and_unknown_capability_fail_closed | Deny |
| Warehouse scopes по разным действиям | `apps/warehouse/tests/test_access.py:222` test_multiple_roles_do_not_launder_global_view_into_operations | all-view не даёт операции в чужой ветке |
| Warehouse stale actor/revocation/department | `apps/warehouse/tests/test_access.py:259`, `:280` | PermissionDenied после отзыва/изменения |
| Waiting List scope/status из разных grants | `apps/waiting_list/tests.py:690` WaitingListPolicyTests.test_waiting_policy_does_not_union_scope_and_status_from_different_roles | Синтетически собранный grant не появляется |
| Waiting List manager без права | `apps/waiting_list/tests.py:593`, `:609` | Edit и transition запрещены |
| Waiting List superuser/global graph | `apps/waiting_list/tests.py:730` test_global_transition_graph_limits_superuser_for_every_status | Допустимы только глобальные переходы |
| Waiting List чужой объект на HTTP | `apps/waiting_list/tests.py:1040` WaitingListRouteTests.test_foreign_entry_is_hidden_or_forbidden_at_http_boundary | 403/404 без чужих данных |
| Самоназначение делегированного manager | `apps/accounts/tests.py:707`, `:582` | PermissionDenied |
| Superuser self-assignment без подтверждения | `apps/accounts/tests.py:717`, `:590` | Без bound risk confirmation отказ, с подтверждением audit |
| Защищённая роль | `apps/accounts/tests.py:745` test_manage_roles_actor_can_assign_ordinary_but_not_protected_role | Обычная роль доступна, protected отказ |
| Protected-before/after/held role | `apps/settings_center/tests.py:714`, `:2421` | Только superuser для protected, self-role edit запрещён делегату |
| Strict protected types | `apps/settings_center/tests.py:4139` LeanRoleAdministrationAuthorityTests.test_protected_capabilities_use_strict_effective_semantics | Ошибочные типы закрывают доступ |
| Технические flags | `apps/accounts/tests.py:861`, `:871`, `:912` | Только superuser + preview/confirmation/audit; нельзя снять собственный флаг |
| Отключение себя/последнего superuser | `apps/accounts/tests.py:924` test_profile_service_rejects_self_disable_and_last_superuser_disable | ValidationError, учётки сохранены |
| Stale memberships/profile/identity | `apps/accounts/tests.py:559`, `:618`, `:641`, `:768` | Отказ без частичной записи и ошибочного аудита |
| Свежесть actor в редакторах | `apps/settings_center/tests.py:219`, `:4485` | Отозванная authority не применяется |
| Переход role file → DB сохраняет границы | `apps/settings_center/test_access_database_slice.py` | Отдельный набор DB-slice, требуется запуск основным агентом |
| Generic writer обхода role editor | `apps/settings_center/tests.py:1921`, `:4189` | Redirect либо отказ; нельзя создать/удалить роли напрямую |
| Неправильные flags/unknown capability/default role | `apps/workorders/tests.py:2664`, `:2675` | ValidationError |

Существующий сквозной management-command: `apps/accounts/management/commands/access_management_e2e.py`; дополнительно `apps/warehouse/management/commands/warehouse_acceptance_e2e.py`. Здесь команды НЕ запускались.

## 6. Пробелы и границы готовности

- Не найдены снимок p50/p95, SQL counts и фиксированный корпус 1k+ для ACCESS-00. SQL perf надо мерить на синтетических данных отдельно от production; одно измерение нельзя выдавать за baseline production.
- Не найдены исполняемые профили без WorkOrders / без всех трёх модулей: это ожидаемый будущий BM-01..05, а не текущее обещание. Статическая связность выше предсказывает import/init failures при раннем удалении apps.
- Waiting List low-level read selector не перечитывает actor; в изученных тестах есть stale write tests, но теста read selector с заранее prefetch-нутыми группами после revoke/deactivation не найдено. Требуется зафиксировать текущее поведение и отдельно решить, является ли это дефектом границы.
- WorkOrders can_view и queryset видимости имеют разные границы Board ACL; golden должен отдельно покрыть оба уровня. Нельзя подменять проверку доступности объекта одним scope_matches.
- Не найден отдельный unit test WorkOrders transition с взаимоисключающими scope/targets двух ролей в просмотренном tests.py; код сохраняет грант целиком, но требуется явная golden case.
- `user_roles` использует groups.values_list и не переиспользует list-prefetch автоматически; Warehouse перечитывает actor на каждом policy call. Возможный N+1 нужно измерить, не исправлять в ACCESS-00.
- Whole-role resolver предполагает валидный contract dict; malformed role value может выбросить TypeError. Contract failure behavior различается по boundary; безопасное поведение для ошибочных payload надо фиксировать по публичным потребителям, а не сочинять общее deny.
- Не проверены production host backend/overrides, реальные memberships/audits, backups и восстановление, внешние Telegram/Bitrix identity links, полноценная матрица AI/MCP/runtime делегирования и все Memory ACL retrieval paths. Эти зоны нельзя объявлять принятыми по данному отчёту.

## 7. Полный индекс прямых текстовых обращений к role resolver/document

Ниже собственный воспроизводимый статический индекс только production Python/HTML (тесты исключены); включает lazy imports, но не динамически построенные имена и не заменяет трассировку исполнения. Значения строк не выводятся.

- `apps/accounts/access_contracts.py`: 23, 128, 135, 172, 178, 183, 186, 314, 364, 392, 453, 651, 789, 1043, 1045, 1051, 1075, 1083, 1090, 1336
- `apps/accounts/config_documents.py`: 2, 5, 6, 9, 10, 19, 22, 24, 31
- `apps/accounts/management/commands/access_management_e2e.py`: 158, 161
- `apps/accounts/management/commands/seed_roles.py`: 18, 19, 49
- `apps/accounts/selectors.py`: 78, 93, 102
- `apps/accounts/services.py`: 92, 93, 94, 99, 128, 129, 130, 131, 132, 138, 152, 182, 293, 294, 295, 327, 328, 342, 374, 471, 472, 473, 475, 516, 517, 543, 867, 868, 869, 882, 903, 914, 923, 924, 1019, 1202, 1203, 1206, 1220, 1378, 1379, 1390, 1404
- `apps/ai/page_context.py`: 151, 154, 164, 183, 186
- `apps/ai/services.py`: 13, 531, 809, 821
- `apps/ai/skill_authoring.py`: 33, 35
- `apps/ai/tool_definitions.py`: 526, 531
- `apps/ai/tooling.py`: 257, 258, 259
- `apps/core/contract_drift.py`: 189
- `apps/core/contract_store.py`: 31, 50, 55, 57, 74
- `apps/core/forms.py`: 7, 51, 59
- `apps/core/management/commands/seed_demo_data.py`: 6, 220, 221, 226, 232
- `apps/core/management/commands/validate_architecture_contracts.py`: 57, 67, 125, 126
- `apps/core/settings_descriptors.py`: 7, 12, 20
- `apps/core/urls.py`: 29
- `apps/memory/policies.py`: 122, 491, 496
- `apps/settings_center/access_migration_services.py`: 53, 56, 225, 463, 603, 814, 845, 894, 897, 1032, 1040, 1041
- `apps/settings_center/contract_services.py`: 85, 198, 243, 253, 398, 416, 501, 520, 617, 719, 767, 769, 782, 789, 833, 920, 923, 962, 1040, 1120, 1228, 1232, 1236, 1245, 1247, 1253, 1367, 1372, 1374, 1383, 1388, 1672
- `apps/settings_center/descriptors.py`: 86
- `apps/settings_center/document_migration.py`: 75, 375, 498, 972, 979, 985, 1010, 1019, 1068, 1121
- `apps/settings_center/document_registry.py`: 28
- `apps/settings_center/document_services.py`: 644
- `apps/settings_center/forms.py`: 329
- `apps/settings_center/management/commands/access_administration_e2e.py`: 89, 90, 92, 97, 103, 104, 111, 112, 117, 118, 125, 128, 130, 178, 179, 231, 280, 330
- `apps/settings_center/management/commands/settings_documents_migrate.py`: 47, 53, 57
- `apps/settings_center/registry.py`: 19
- `apps/settings_center/views.py`: 392, 439, 1045, 1079
- `apps/waiting_list/policies.py`: 1, 18
- `apps/waiting_list/selectors.py`: 5, 33
- `apps/waiting_list/services.py`: 7, 102, 168, 253
- `apps/waiting_list/views.py`: 37, 38, 40, 41, 76, 114, 134, 198, 245, 273, 281, 341
- `apps/warehouse/policies.py`: 12, 55, 57
- `apps/workorders/contracts.py`: 217
- `apps/workorders/policies.py`: 67, 92, 93, 98, 116, 119, 136, 139, 205, 226, 235, 273, 298, 306, 313, 338, 377, 387, 393, 408, 417, 437, 452
- `apps/workorders/services.py`: 72, 73, 76, 78, 198, 199, 200, 222, 462, 517
- `services/agent_runtime/tools.py`: 333, 334, 337, 440
