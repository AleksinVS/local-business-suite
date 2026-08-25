# Упрощённая архитектура управления доступом

Статус: целевая модель принятого ADR-0043.

Фактическое поведение до завершения миграции описано в `POLICY_MODEL.md`.

## 1. Граница решения

```text
User
 ├─ explicit contract roles (Django Group)
 ├─ is_staff: Django Admin entry only
 ├─ is_superuser: reserve full product access
 └─ technical groups: domain-owned exceptions

role_rules.json
 ├─ frozen $capabilities metadata
 └─ runtime-editable roles and flat grants

Decision
 = active user
 AND (
   active superuser reserve
   OR one whole contract-role grant
   OR explicit domain technical authority
 )
 AND applicable object scope, resource ACL and workflow
```

Система не получает общий compiler, registry evaluator, policy DSL или внешний
runtime. Доменные policy/selector/service остаются источником исполнения.

## 2. Модель роли

Роль содержит:

- стабильный code;
- название и описание;
- `protected`;
- текущие flat capability values.

Обычная роль редактируется и назначается active actor с `manage_roles`.
Защищённая роль — только active superuser.

Защита роли определяется так:

```text
role.protected is true
OR role contains a code-owned PROTECTED_CAPABILITIES capability
```

Исходный `PROTECTED_CAPABILITIES` сохраняет все текущие effective
`risk=critical` права: `manage_roles`, `manage_settings`, `manage_ai_skills`,
`memory_organization_review`, `create_waiting_list` и все `waiting_list_*`
права просмотра, изменения и переходов. Набор хранится в коде, потому что его
изменение меняет границу административной власти.

Для изменения роли используется `protected_before OR protected_after`.
Явный флаг `protected` меняет только active superuser.
Effective grant: flag=`true`; scope — валидное значение кроме `none`; targets —
непустой валидный набор или `*`. Неизвестный/невалидный тип или значение
fail-closed считается protected. Правило применяется к before и after.

## 3. Администрирование

| Операция | `manage_roles` | active superuser |
|---|---:|---:|
| Назначить обычную роль другому пользователю | да | да |
| Создать/изменить обычную роль | да | да |
| Изменить или назначить собственную роль | нет | да |
| Изменить/назначить protected role | нет | да |
| `is_staff`, `is_superuser`, AD identity, technical groups | нет | да |

Скрытые allowlists редакторов и назначений не используются. UI показывает
причину недоступности операции через обычную/защищённую роль.

Удаление роли отложено: до отдельного решения нельзя безопасно изменить
семантику Django Group, Board ACL, `role:<code>` memory tokens и GroupProfile.
Создание роли проверяет reserved/invalid code и коллизии с существующей
технической, AD или memory-группой. Django Group и GroupProfile материализуются
идемпотентно штатным сервисом/`seed_roles`, а не произвольной записью формы.

## 4. Доступ к разделам сайта

Раздел сайта — read-only проекция эффективных grants, а не отдельное назначение.
Текущая небольшая code-owned карта `capability -> UI section` остаётся
канонической для отображения и имеет coverage-test. Неизвестное право попадает
в «Прочие» и не скрывается.

Отдельный JSON-каталог presentation metadata не создаётся.

## 5. Доменные scopes

Текущие `flag/scope/targets` сохраняются на первом этапе. Для одной операции
нельзя взять scope одной роли и statuses другой: policy перебирает роли как
целые кандидаты.

Возможное последующее упрощение листа ожидания:

- один view scope;
- один edit scope;
- список текущих статусов, в которых редактирование разрешено;
- boolean смены статуса;
- целевой статус задаёт только глобальный workflow.

Такое изменение выполняется лишь после business matrix и отдельной приёмки —
оно может изменить фактический доступ.

## 6. Явные роли

Скрытый `default_board_viewer` заменяется явной least-privilege ролью `viewer`,
которая повторяет только `view_scope=department_branch` и не даёт прав записи.

Миграция:

1. read-only отчёт активных пользователей без контрактной роли;
2. явное решение владельца `viewer` / `customer` / другая роль / «без роли» по
   каждому пользователю с показом точного access delta;
3. аудируемое применение утверждённого runtime manifest без значения по
   умолчанию;
4. повторный отчёт под access lock и переключение только после классификации
   каждого пользователя без роли;
5. owner-reviewed список досок с ACL `customer`, добавление `viewer` через
   locked Board service с `BoardAccessAudit`, сохранением `customer`, проверкой
   версии/конкурентного изменения и сервисным rollback;
6. HTTP/e2e проверка отсутствия скрытого доступа и сохранения набора досок.

Технические-only пользователи классифицируются отдельно. Новые пользователи не
получают роль автоматически.

## 7. Пути записи

### Product UI

Один request `Сохранить`:

```text
parse form
-> read fresh actor/target
-> acquire access lock
-> re-read role contract or DB rows
-> authorize
-> validate candidate
-> atomic write/transaction
-> audit
```

Существующий внутренний подписанный plan внутри того же request пока остаётся:
он не виден пользователю и его удаление не требуется для смены authority model.
Отдельный рефакторинг может заменить его после доказательства эквивалентности
подблокировочной авторизации. Access mutation для AI отключается.

### Django Admin

Резервный путь только для active superuser. Причина обязательна; использование
видно в аудите. Django Admin не редактирует `$capabilities`.

### AI

ИИ объясняет доступ, находит пользователя/роль, открывает и может предзаполнить
редактор. Изменение применяется человеком кнопкой `Сохранить`. Серверный AI
access-write tool удаляется после проверки клиентов. `department_id` является
access-полем из-за branch scope; вместе с `is_active`, username, ролями,
техническими группами, privileged flags и AD identity он никогда не изменяется
ИИ.

### AD

AD синхронизирует identity и профиль. Role sync остаётся выключенным. Его
возврат потребует отдельного требования, system actor и предметного аудита.

## 8. Что сохраняется как надёжная внутренняя сложность

Скрытая от пользователя сложность не удаляется только ради уменьшения числа
строк. Сохраняются:

- atomic replace и CAS файлового role contract;
- короткий access lock и DB transaction;
- свежая проверка actor непосредственно перед записью;
- selectors для списков;
- ACL досок, файлов и memory sources;
- last-superuser guard;
- audit before/after/source/reason;
- fail-closed для неизвестных значений.

Staged `PENDING/INCONSISTENT` protocol остаётся общим механизмом runtime
contracts. Удалять его из access-пути можно только после отдельной миграции
ролей в DB, а не частичным упрощением файловой записи.

## 9. Что удаляется или не вводится

- runtime-изменение `$capabilities`;
- `$administration` editor/assignment allowlists;
- capability risk levels как продуктовая метаполитика;
- пользовательский confirmation checkbox; внутренний signed plan одного Save
  пока остаётся реализационной деталью;
- `default_board_viewer`;
- ложные direct Django permission sources в explain/UI;
- самостоятельная access mutation со стороны AI;
- автоматический AD role sync;
- `EvaluatorSpec`, `binding_id`, compiler, общий `authorize()` и `Decision`;
- отдельный UI metadata contract;
- structured grants и technical-group registry без подтверждённого дефекта.

## 10. Deployment-изменение capability catalog

Обычный writer под общей блокировкой одновременно требует:

```text
hash(runtime.$capabilities) == hash(git_default.$capabilities)
AND candidate.$capabilities == runtime.$capabilities
```

Инвариант действует для apply, rollback, generic и constrained writer. Перед
включением guard Git-дефолт и runtime catalog обязаны совпадать.

Единственный путь обновления catalog — отдельная management command для
deployment с обязательными expected current-runtime и target-Git hashes, общей
access-блокировкой, полной contract/cross-contract validation, резервной копией
и записью оператора. Только она может выполнить строго проверяемый переход при
временном несовпадении двух хешей.
Команда не вызывается из Settings Center, rollback или продуктового UI.

## 11. Минимальная проверочная матрица

- unknown role/capability/scope/status -> deny;
- no role -> no role-derived general access; technical authority remains
  domain-limited;
- ordinary `manage_roles` actor edits/assigns ordinary role;
- non-superuser self-change -> deny;
- protected role edit/assignment -> superuser only;
- every currently effective critical role remains protected;
- superuser self-assignment -> allow + audit;
- `$capabilities` apply/rollback mutation -> deny;
- deployment catalog migration requires matching current-runtime/target-Git
  hashes;
- one whole role satisfies scope+targets;
- foreign object ID -> deny;
- selector result is a subset of point-policy result;
- AI and AD cannot mutate role membership;
- Admin break-glass requires active superuser, reason and audit;
- desktop/mobile direct Save completes without full page reload.
