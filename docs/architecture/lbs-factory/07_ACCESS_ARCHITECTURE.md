# LBS Access — подключаемая система прикладных полномочий

**Статус:** **Accepted — согласованная целевая спецификация LBS Access**, разработанная в v3.3 и включённая в v3.4; не является уже внедрённым изменением или разрешением на изменение production.  
**Основа:** текущие `apps.accounts`, `apps.workorders.policies`, `apps.warehouse.policies`, `apps.memory.policies`, редактор прав и аудит.  
**Контрольный снимок исходников:** `main`, `4ea22b2dcbd6ce5e101b26064b8bfc02a501dfe3`; перед реализацией обязательно повторно сверить репозиторий.

## 1. Принятый принцип

Не разрабатывать новый IAM/authorization engine с нуля. Сохранить существующее направление LBS: **явные роли + типизированные возможности (`flag/scope/targets`) + доменные условия + ACL ресурсов + workflow + аудит и запрет по умолчанию**. Переработать границы и зависимости так, чтобы система прав могла использоваться независимо от WorkOrders и других подключаемых бизнес-приложений.

**LBS Access — одна из заменяемых реализаций прикладной авторизации (AuthorizationProvider), а не обязательный центральный сервер во всех внедрениях.** Для профиля, использующего внешнюю систему авторизации, нужен соответствующий адаптер. Но гарантии проверки прав, идентичности и аудита не являются отключаемой опцией для сетевого корпоративного доступа. В автономном техническом CLI допускается явно ограниченный локальный профиль без корпоративных пользовательских полномочий.

Не смешивать:

1. **Authentication:** кто совершает запрос? Local / LDAP / AD / OIDC (authentik, Keycloak) и проверенная session/service identity.
2. **Identity linking:** какой реальной учетной записи соответствуют Telegram, Bitrix24 и другие внешние идентификаторы?
3. **Authorization:** какие capabilities и области доступны субъекту?
4. **Domain enforcement:** можно ли совершить конкретную операцию над конкретным объектом прямо сейчас?
5. **Approval:** согласовано ли конкретное потенциально опасное действие? Согласование не заменяет проверку прав.

## 2. Существующая реализация: сохраняемое и исправляемое

| Наблюдение в коде | Сохраняем | Исправляем |
|---|---|---|
| `apps.accounts` на Django `User/Group`, `ExternalIdentity`, `GroupProfile`, аудиты | Редактор ролей, явные назначения, защищённые роли, проверки stale actor, аудит, last-superuser guard | Зависимость от бизнес-домена заявок; переносим общую логику за собственный port |
| `contracts/role_rules.json` и ADR-0043 | Плоские роли, `flag/scope/targets`, whole-role evaluation, runtime-неизменяемые описания возможностей | Специальные capability-коды предметных модулей не должны быть захардкожены в accounts |
| `apps.workorders.policies` | Scope по авторству/назначению/ветке подразделений, проверки workflow и ACL доски | `active_role_rules`, общее определение grants и разрешение оргструктуры не должны принадлежать WorkOrders |
| `apps.warehouse.policies` | `require_warehouse_scope`, предметные проверки под блокировкой, запрет без назначения подразделения | Прямой импорт `apps.workorders.policies` и знание чужих ролей |
| `apps.memory.policies` | Классификация, ACL, аудит чтения, scope tokens, запрет непроверенному субъекту | Стандартизировать actor context и разрешение авторизации; сохранить собственные ограничения Wiki |
| `apps.waiting_list.services` | Доменную проверку работы с персональными данными | Убрать импорт `role_rules` из WorkOrders |

**Не удалять существующую семантику из ADR-0043.** Текущие правила `one whole role grant`, fail-closed, проверка активного субъекта перед записью, запрет AI на изменение ролей и разделение технических групп — обязательные инварианты миграции.

## 3. Архитектурные границы

```text
                    Local / LDAP / AD / OIDC
                          │ verified principal
        Telegram/Bitrix24 ─┤ identity linking (verified, audited)
                          ▼
                    TrustedActorContext
                          │
                    AuthorizationProvider
                  /          |            \
         role grants     capability      authority
         + snapshots     metadata        snapshot
                  \          |            /
                   domain-owned policy
                  /        |         \
           LLM-Wiki    WorkOrders     Warehouse / Bitrix
               │        │               │
        object ACL      status/board     stock & external owner checks
               └────────┴───────────────┘
                     decision + audit
```

- **IdentityProvider:** проверяет подлинность, предоставляет устойчивый `subject_ref` в рамках установки; НЕ назначает прикладные права по умолчанию.
- **IdentityLinkProvider:** подтвержденно связывает внешние ID с существующим субъектом. Совпадение имени, номера телефона или электронной почты не является доказательством идентичности.
- **AuthorizationProvider:** разрешает субъекту доступные роли и grants; управляет назначениями. Реализация `lbs-access` базируется на существующих моделях Django, но предоставляет явный порт.
- **CapabilityCatalog:** собирает *декларации* возможностей подключаемых модулей; **описание возможности не является разрешением**, а `enabled` не является `allowed`.
- **DomainPolicy:** окончательная проверка конкретной операции над ресурсом, с его актуальным состоянием и внешними ограничениями. Логика остаётся в владельце предметной области.
- **AuditSink:** фиксирует изменения полномочий и критические решения; реализация может переиспользовать существующие audit-модели и correlation IDs.

В компактном профиле все интерфейсы могут выполняться локально в Django; отдельный authorization HTTP service не обязателен. При service extraction появляется адаптер, но не второй источник прав.

## 4. Семантика решений

Для конкретной операции используются **все** условия:

```text
installed_and_enabled(component)
AND verified_active_principal
AND valid_effective_role_grant(capability, scope, targets)
AND domain_scope_allows(actor, resource)
AND resource_acl_allows(actor, resource)
AND business_state_allows(action, resource)
AND external_owner_allows_if_applicable(action, resource)
AND approval_is_valid_if_required
```

Для отдельной политики, не использующей внешний владелец или approval, соответствующее условие считается **неприменимым**, а не искусственно «разрешенным». Никакая из остальных проверок не может компенсировать отсутствующее ролевое разрешение. Допущенные в ADR-0043 технические authority исключения сохраняются как узкие явные доменные полномочия, а не универсальный обход роли.

**Whole-role evaluation:** связанное `scope` и `targets` одной роли нельзя комбинировать с разрешением другой роли для получения более широкого составного grant. Точное правило проверки соответствует ADR-0043 и не меняется автоматически при рефакторинге.

**Зависимости:** модуль *регистрирует* возможности и их описания, а не изменяет центральный `access_contracts.py`; для параметризованных областей он предоставляет доменный валидатор/selector. Не строим универсальную DSL, evaluator registry, distributed PDP или полную иерархию ролей в первом срезе.

## 5. Лёгкие интерфейсы v1

Это **псевдоконтракты** уровня application service, не требования к новым HTTP endpoint и не универсальный вычислитель политик.

```python
@dataclass(frozen=True)
class TrustedActorContext:
    installation_id: str
    subject_ref: str             # stable local ID, not client-supplied
    actor_kind: str              # user | service | agent
    verified_auth_ref: str       # server-side session/credential reference
    originating_subject_ref: str | None
    agent_ref: str | None
    correlation_id: str

class IdentityProvider(Protocol):
    def authenticate(self, credential_ref: str) -> TrustedActorContext: ...

class AuthorizationProvider(Protocol):
    def grants_for(self, actor: TrustedActorContext) -> tuple["Grant", ...]: ...
    def access_revision(self, actor: TrustedActorContext) -> str: ...

class CapabilityContributor(Protocol):
    def capabilities(self) -> tuple["CapabilitySpec", ...]: ...

class DomainAccessPolicy(Protocol):
    def visible_queryset(self, actor: TrustedActorContext, query): ...
    def require_action(self, actor: TrustedActorContext, action: str, resource): ...
```

- Реализация `visible_queryset` применима к локальному ORM; внешние providers могут использовать иной query/selector port. Не требуется насильно унифицировать все SQL/Bitrix фильтры в одно представление.
- `grants_for()` предоставляет **кандидаты** ролей; `require_action` подтверждает доступ к объекту. Не вводить общий `authorize()` как новую доменную истину, пока не появилась конкретная потребность.
- Никакого клиентского `subject_ref`, `roles`, `department_id`, `agent_ref` из тела tool-вызова в качестве полномочия.
- При сетевой границе доверия — аутентифицированная service identity + ограниченный подписанный/opaque delegated authority reference, short TTL, installation binding, audience и проверка отзыва. Не передавать полномочия через обычные заголовки `X-User-Id`.

## 6. Регистрация capability подключаемыми модулями

Пример *предлагаемого* descriptor, не существующего формата текущих JSON-контрактов:

```yaml
module: warehouse
capabilities:
  warehouse.view:
    type: scope
    values: [none, own_department, department_branch, all]
  warehouse.issue:
    type: scope
    values: [none, own_department, department_branch]
  warehouse.adjust:
    type: scope
    protected: true
  warehouse.manage_catalog:
    type: flag
    protected: true
```

- При изменении кода публикуются новые metadata и проходят contract tests; **администратор не редактирует кодовые описания capabilities из UI**.
- Роли и назначения хранятся в одном выбранном authorization provider. Подключение модуля не выдаёт новых прав по умолчанию.
- `disabled`: определения и назначения сохраняются, но их effective rights равны запрету, HTTP/UI/AI/MCP endpoints не доступны; background jobs учитывают новое состояние.
- `uninstalled`: только после анализа миграций, внешних ссылок и retained data; не означает автоматического удаления ролей или таблиц.
- Переименование кодов — только через versioned migration + alias/deprecation window, без тихой смены смысла grants.
- Исходный `$capabilities`/`role_rules.json` остаётся действующим на первом этапе. Каталог собирается как **проекция** из зарегистрированных descriptors, затем переключается в единый канон; два независимых редактируемых каталога запрещены.

## 7. Пользовательская идентичность и внешние системы

| Источник | Что подтверждает | Чего не подтверждает |
|---|---|---|
| Local account | Вход локального пользователя | Полномочия Битрикс24 |
| AD/LDAP/OIDC | Корпоративная идентичность / аутентификация | Права на отдельный документ Wiki без LBS/доменных политик |
| Telegram `user_id` | Участника/отправителя на стороне канала после корректной валидации update | Его корпоративную роль и AD-учётку |
| Bitrix24 user ID / OAuth | Субъекта в конкретном портале, доступный API scope | Все корпоративные права за пределами Битрикс24 |

Нужен `ExternalIdentityLink` с `installation_id`, `provider_code`, `external_subject_id`, `subject_ref`, способом подтверждения, временем привязки/отзыва и аудитом. Переиспользовать существующий `ExternalIdentity`, **расширять только если необходимого поля/семантики нет**, без дубля identity tables. Нельзя автоматически объединять идентичности по ФИО/email.

Взаимодействие с Битрикс24: источник истины прав на объекты Битрикс — сам Битрикс24, включая его настройки прав, согласия OAuth и scopes. LBS Access добавляет ограничения, но не объявляет API токен полномочием пользователя; при интеграции от имени пользователя нужна корректная схема token-on-behalf-of или функционально ограниченный сервисный доступ, с отдельным audit.

## 8. Агенты и делегирование полномочий

Три режима: (а) агент действует в рамках интерактивной пользовательской сессии; (б) системный агент работает с явно выделенными service grants; (в) один агент делегирует часть задания другому.

Никогда не расширять `effective grants` при делегировании:

```text
allowed(task action) =
  originating_subject_grants
  INTERSECT requesting_agent_authority
  INTERSECT executing_agent_authority
  INTERSECT task_constraints
  INTERSECT current_domain_policy
```

`INTERSECT` — концептуальное пересечение **полных grant-предикатов**, а не поэлементное склеивание полей `scope/targets`. Исключение: системная задача без пользовательского инициатора использует собственный service principal и его явный ограниченный набор grants; нельзя подставлять «администратора» как отсутствующего пользователя.

- В `AgentTask` передавать `initiator`, `delegation_ref`/`policy_ref`, `allowed_capability_refs`, `context_refs`, expiry; **не помещать переносимые bearer secrets и доверенные роли в обычный JSON**.
- A2A и MCP не аутентифицируют бизнес-пользователя автоматически. Получатель проверяет сеть, сервис, инициатора, audience, TTL и конкретный `delegation_ref`; запрос другого installation_id отклоняется.
- Короткое право агента может быть *сужено* при чтении/выполнении; изменения roles и ACL немедленно учитываются на критическом side effect. Кэширование проверок разрешено только в рамках ограниченного запроса, с описанной моделью отзыва.
- Confirmation может подтверждать конкретное подготовленное действие, но не заменяет прав; запрещены самоподтверждение агентом и privilege escalation через `approved=true`.
- Agent authoring, доступ к инструментам и изменение доступа — разные capabilities. Как и в ADR-0043, AI может объяснить/подготовить редактор ролей, но **не меняет роли, is_staff, is_superuser, department, AD identity через собственный tool** в базовом профиле.
- Каждая существенная операция фиксирует `installation_id`, проверенные principal refs, task/correlation id, capability, цель, решение, policy revision, результат, без сырого prompt/PII в техническом логе.

## 9. LLM-Wiki, групповые комнаты и Telegram

**Wiki:** проверка прав на закрытые источники до ответа модели сохраняется. Безопасная рабочая запись knowledge.save_working доступна без reviewer; needs_confirmation не блокирует поиск и виден в отдельном реестре. Старый lifecycle=pending остаётся скрытым от обычного поиска; официальный выпуск и изменение закрытого доступа — отдельные полномочия.

**Группы:** чтение закрытого Wiki для генерации ответа, который будет опубликован в комнате, допускается только по аудитории выдачи. При известном подтверждённом составе участников применяем ограничение всех получателей и room-level policy. При неизвестной/динамической аудитории, в частности внешней Telegram-группе, закрытые источники не использовать и закрытые результаты не публиковать — предложить персональный защищённый канал. Проверить аудиторию повторно непосредственно перед публикацией. Не полагаться на отдельные DM-права инициатора.

**Telegram:** Telegram ID не равен корпоративной identity. Связывание — через проверяемое подтверждение в защищённом канале, с expiry и audit. Не публиковать сырой перечень разрешённых документов в общую группу. Read-only discovery анкета допускает анонимное общение только в явно открытом/синтетическом режиме; доступ к внутренним знаниям — после linking.

**Web Chat:** членство в комнате не равно доступу к любому документу, который упомянул участник. Пересчитывать права на отправку и fetch сообщения/артефакта; архивная запись может становиться недоступной после отзыва допуска согласно retention/security policy.

## 10. Администрирование, хранение и аудит

- Сохраняем единый пользовательский редактор ролей, обычные/защищённые роли, `manage_roles`, запрет self-escalation и last-superuser guard.
- До отдельного ADR хранилище определений ролей **не переносить автоматически** из `role_rules.json` в БД. Учитывать действующий ADR-0048 и реальный статус `database_override` на каждой среде; rollback после миграции обязателен.
- Нельзя смешивать терминологию `runtime module enabled` и `role grant enabled` в UI.
- Домен сохраняет свои аудиты критических операций; общий `correlation_id` позволяет связать их с назначением роли, подтверждением и AgentTask. Не копировать всё в единую огромную «таблицу событий безопасности».
- Деактивация пользователя/удаление роли должны прекращать новые операции и выдачу приватных данных; операционные отчёты показывают фактически действовавшие права на время события.
- Отдельная ручная break-glass процедура с повышенной аутентификацией, ограниченным доступом и аудитом. Текущий superuser — резервный механизм, не общий сервисный principal.

## 11. Готовые внешние решения: что предусмотреть, но не внедрять заранее

- **authentik или Keycloak:** внешний IdentityProvider (OIDC/SSO); не переносить весь редактор прикладных ролей в Identity Provider.
- **OpenFGA:** возможная доменная реализация ACL отношения `user -> group -> room/document/project` для настоящих сложных sharing scenarios. Пилот допустим только с доказанной потребностью иявно определённым владельцем политики/отношений; не создавать два источника истины.
- **OPA:** возможен при появлении сложных централизованных правил контекстной авторизации, не для первого внедрения.
- Текущие `flag/scope/targets` + Django Group + domain selectors должны остаться reference implementation для компактного профиля.

## 12. Приёмочные инварианты

1. `apps.accounts` загружается и управляет ролями без `apps.workorders`.
2. Warehouse/WaitingList/LLM-Wiki не импортируют правила ролей из WorkOrders.
3. Включение нового модуля регистрирует capabilities, **но не назначает grants**.
4. `disabled` модуль не разрешает вызовы через HTTP/UI/AgentTask/MCP, при повторном включении назначения не потеряны.
5. Пользователь без роли по умолчанию не получает бизнес-доступа; protected roles и last-superuser guard сохранены.
6. Поддельные идентификаторы/роли/подразделение из JSON/Telegram/A2A отклонены.
7. Делегирование между двумя агентами не повышает права на Wiki, склад и задачи.
8. Групповой чат с неизвестной аудиторией не показывает закрытые данные (включая фрагменты и citations).
9. После отзыва роли активный AgentTask не может выполнить ранее подготовленную защищённую запись.
10. Bitrix24 API не позволяет обойти запрет локальной политики либо ограничения внешнего владельца.
11. Применение ролей и действий имеет audit/correlation, а восстановление/rollback не теряет историю.
12. Минимальный профиль не зависит от OpenFGA/OPA/Keycloak и не требует сетевого вызова PDP на каждую строку.

## 13. Связанные решения и документация

Исходники: `apps/accounts/{models.py,services.py,access_contracts.py}`, `apps/workorders/policies.py`, `apps/warehouse/policies.py`, `apps/memory/policies.py`, `apps/waiting_list/services.py`, `contracts/role_rules.json`.

Основные ADR: `ADR-0040` (администрирование), `ADR-0043` (простая модель доступа), `ADR-0045` (закрытый доступ без роли), `ADR-0046` (иерархия отложена), `ADR-0048` (настройки), `ADR-0041` (области блокировок), `ADR-0034` (capability metadata). При развитии Factory нужен новый ADR, дополняющий принятые решения, а не безмолвная замена исходных исторических ADR.

## 14. OpenFGA как опциональный ресурсный backend (v3.4)

LBS Access остаётся владельцем ролей и capability grants, а домены — бизнес-ограничений. Для отношений конкретных LBS-owned объектов (Wiki, комнаты, проекты) предусматривается лёгкий ResourceRelationshipBackend с LocalResourceACL по умолчанию. **OpenFGAResourceACL реализовать только при реальном пересекающемся sharing/наследовании прав**, сначала на одном типе объекта; без копирования прав Битрикс24/1С.

После подключения у данного типа объекта только **одна** writable authority отношений. Сверить локальные и OpenFGA решения на golden tests, выполнить backfill/cutover и проверить отказ; нет silent allow. Подробнее: [09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md](09_PROGRESSIVE_COMPLEXITY_AND_OPENFGA.md).

## 15. Разделение прав и privacy-преобразования

LBS Access (и optional OpenFGA) решает, **кто** может обратиться к ресурсу; Content Privacy Pipeline решает, **какое содержимое** допустимо в конкретном `destination` — поиск, Wiki Git, агентный контекст, внешняя модель. Успешный `adapter_check` не разрешает raw egress. `original_read` для врача/оператора остаётся отдельным предметным действием с проверкой прав.

При отказе преобразования нельзя подставлять raw filename, object_id, source_uri или полный текст. Подробнее: [10_CONTENT_PRIVACY_PIPELINE.md](10_CONTENT_PRIVACY_PIPELINE.md).
