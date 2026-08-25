# План упрощения управления ролями

Статус: Completed 2026-08-25; runtime cutover роли `viewer` остаётся отдельной
операцией владельца после утверждения полного списка пользователей и досок.

## 1. Цель

Сократить действующую метаполитику и отказаться от новой универсальной
платформы авторизации, сохранив server-side object authorization, domain
services, атомарность и аудит.

## 2. Non-goals

- DB-миграция role definitions;
- новые capability-коды;
- structured grants;
- общий compiler/authorize/Decision;
- OPA/Cedar;
- упрощение workflow semantics без отдельной business matrix;
- автоматический AD role sync;
- общий registry memory technical groups;
- удаление ролей;
- удаление внутреннего signed plan прямого Save;
- новая навигационная структура единого окна доступа.

## 3. Definition of Ready

- ADR-0043 принят;
- для каждого пакета указан точный read/write scope;
- изменения `default_board_viewer` отделены миграционным gate;
- пересекающиеся остатки пакетов 04/05 ADR-0040 закрываются либо явно входят в
  package 05 этого блока; параллельного изменения одного UI/объяснения нет;
- реализация выполняется в `feature/lean-access-control`;
- документационный baseline commit и feature push выполняются до изменения кода,
  но только после Sol high review;
- последующие feature push, merge в main и main push проходят после финального
  Sol high review.

## 4. Порядок пакетов

### Pre-00. Documentation baseline — основной агент + Sol high

- Принять lean ADR и исправить связанные ADR/architecture/planning документы.
- Gate: Sol high PASS, затем documentation-only commit и push feature-ветки до
  любого изменения Python, шаблонов, контрактов или тестов.

### 00. Golden matrix — основной агент + Sol high

- Зафиксировать capability/role/source matrix.
- Добавить golden tests текущего поведения без его изменения.
- Явно отделить pre-migration tests от target tests последующих пакетов.
- Gate: целевые быстрые тесты текущей модели.

### 01. Freeze capability metadata — основной агент/Sol high

- До включения guard сверить нормализованные Git/runtime `$capabilities`.
- Запретить изменение `$capabilities` через apply, rollback, generic writer и
  constrained Save безусловным under-lock invariant.
- Добавить deployment-only команду обновления catalog с expected
  current-runtime/target-Git hashes, access lock, backup, validation и operator
  record.
- Gate: прямой service, rollback, constrained/generic write и hash-mismatch tests.

### 02. Disable AI/AD access mutations — основной агент/Sol high + Luna high

- AI access mutation заменить explain/open/prefill behavior в dispatcher,
  Python-каталоге и Git-default AI tools contract.
- Runtime AI tools изменить только штатной операционной миграцией.
- Полностью убрать write behavior `access.users.update`: `department_id` меняет
  branch scope, а `is_active` — сам доступ. AI не меняет также роли/группы,
  privileged flags, username и AD identity.
- AD role sync оставить fail-closed; identity/profile sync не менять.
- Gate: AI/AD cannot mutate; AI profile-only boundary; contracts profile.

### 03. One role administration authority — Sol high

- Сделать `manage_roles` единственным product authority.
- Добавить explicit `protected` и полный code-owned
  `PROTECTED_CAPABILITIES`, сохраняющий текущие critical boundaries.
- Проверять `protected_before OR protected_after`.
- Разрешить create/edit/assign ordinary roles; удаление не реализовывать.
- При создании проверять reserved/invalid code и коллизии с technical/AD/memory
  groups; Group/GroupProfile материализовать идемпотентно.
- Сохранить no-self/held-role change для non-superuser и полный
  active-superuser path.
- Удалить `$administration` allowlists после совместимой миграции.
- Gate: полная actor/target/protected/create matrix service + HTTP.

### 04. Explicit viewer migration — основной агент/Sol high + Luna high

- Добавить ordinary role `viewer`, точно повторяющую read-only профиль.
- Создать read-only отчёт активных пользователей без роли с отдельной
  классификацией technical-only users и точным access delta.
- Применять только owner-approved runtime manifest с явным выбором
  `viewer/customer/other/no-role`; значения по умолчанию нет.
- Под access lock повторить отчёт и требовать классификацию каждого roleless
  user перед отключением `default_board_viewer`.
- Включить owner-reviewed список досок, открытых `customer`; через canonical
  Board service добавить `viewer` с audit, version/concurrency check и
  сервисным rollback, не удаляя `customer`.
- Gate: no hidden role-derived access, technical authority parity,
  policy/selector/HTTP/e2e.

### 05. Explain cleanup — основной агент/Sol high + Luna high

- Убрать direct Django permissions из explain/UI, если policy их не читает.
- Проверить реальные membership memory technical groups; объединение групп —
  только отдельным решением по данным.
- Gate: explain matches enforcement; memory behavior unchanged.

### 06. Minimal UI adaptation — Luna high + Luna xhigh critic

- Сохранить существующее одно окно и текущие разрезы ADR-0040.
- Добавить ordinary/protected labels, создание роли и миграционную видимость.
- «Разделы сайта» оставить read-only projection.
- Не смешивать advanced identity/memory fields с role grants.
- Gate: desktop/mobile, keyboard, direct Save, errors и browser e2e; затем
  явная пользовательская приёмка.

### 07. Final acceptance — основной агент + Sol high

- `make verify-fast` по пакетам;
- `make verify-profile PROFILE=contracts|ai|memory|ui`;
- один `make verify-full`;
- architecture contracts и structure generation;
- зафиксировать owner approval миграции и UI, сформировать финальные отчёты,
  архивировать planning/workflow, удалить backlog item и обновить структуру;
- зафиксировать все изменения одним clean feature commit и получить его exact
  SHA; после этого tracked files не меняются;
- Sol high security/code review этого SHA;
- после PASS — push reviewed feature SHA, merge only this state, проверить main
  merge commit и push main.

## 5. Stop conditions

Пакет останавливается и возвращается на архитектурное решение, если:

- требуется новый общий policy abstraction;
- нарушается whole-role evaluation;
- для упрощения нужно расширить фактический доступ;
- исчезает свежая проверка actor/target под lock;
- AI/Admin/command получает обход доменного service;
- migration пользователей без роли не имеет явного списка и audit trail.

## 6. Отложенные решения

- упрощение waiting-list scopes/status targets;
- перенос role definitions в DB;
- объединение memory technical groups;
- удаление staged runtime-contract reconciliation;
- удаление внутреннего signed plan direct Save;
- lifecycle удаления роли;
- переработка навигации единого окна ADR-0040.

Они рассматриваются только по измеримому использованию и отдельной приёмке.

## 7. Итог

Все пакеты 00–07 реализованы и приняты. Модель сведена к одному контракту ролей,
одной продуктовой возможности `manage_roles`, обычным и защищённым ролям,
предметным проверкам и прямому сохранению. Запись прав через AI и AD отключена;
Django Admin сохранён как резерв. Интерфейс принят на широком и узком экране,
включая сохранение без перезагрузки и восстановление после сетевой ошибки.

Git-дефолт содержит роль `viewer`, но рабочие данные намеренно не изменены:
назначения пользователей и доступ досок требуют отдельного утверждённого
manifest и штатной команды миграции.
