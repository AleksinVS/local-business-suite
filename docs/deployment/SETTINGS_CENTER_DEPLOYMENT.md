# Settings Center Deployment

Статус: deployment note.

Дата: 2026-05-20.

## Required Steps

1. Apply migrations:

```bash
python manage.py migrate
```

В этом блоке также применяются миграции `accounts.0011` (аудируемый системный
bootstrap назначений), `settings_center.0003` (снимки и состояния восстановления
contract audit), `ai.0013` (состояния processing/failed/reconciliation_required),
`workorders.0018` (предметный аудит доступа к доскам) и `memory.0024`
(аудит технических групп памяти).

2. Ensure private deployment `.env` contains explicit Settings Center policy:

```dotenv
SETTINGS_CENTER_ENABLED=true
SETTINGS_CENTER_ENV_APPLY_MODE=proposal
SETTINGS_CENTER_ENV_PROPOSAL_DIR=data/settings_center/env_proposals
SETTINGS_CENTER_HELP_AI_ENABLED=true
SETTINGS_CENTER_HELP_MODEL_PROFILE=local_admin_help_v1
SETTINGS_CENTER_HELP_MAX_CONTEXT_CHARS=6000
SETTINGS_CENTER_AUDIT_RETENTION_DAYS=365
```

3. Configure AD-link and ACL defaults:

```dotenv
ACCOUNTS_AD_LINK_ENABLED=true
ACCOUNTS_AD_LINK_MODE=manual
ACCOUNTS_AD_GROUP_ROLE_SYNC=false
MEMORY_ACL_INHERITANCE_ENABLED=true
MEMORY_ACL_FAIL_CLOSED=true
MEMORY_ACL_UNRESOLVED_POLICY=block
MEMORY_ACL_GROUP_NESTING_DEPTH=5
MEMORY_ACL_CACHE_TTL_SECONDS=3600
```

`ACCOUNTS_AD_LINK_MODE=manual` означает, что LDAP-вход обновляет только безопасно
аудируемые поля профиля и не перезаписывает ручную AD-привязку. Режим
`automatic` разрешайте только если каталог является владельцем principal-связи:
тогда профиль и AD identity меняются под общим lock, одной транзакцией и с
`SettingsChange`.

Оставляйте `ACCOUNTS_AD_GROUP_ROLE_SYNC=false`. В этом срезе даже при `true`
сопоставление AD-групп только проверяется, а изменение ролей безопасно пропускается
с записью ошибки: системный actor и аудируемый AD assignment service ещё не
реализованы. Это может сохранить ранее назначенную локальную роль; контролируйте
журнал приложения при пилоте AD.

4. Обновите рабочие контракты и предопределённые группы:

```bash
python manage.py sync_ai_tool_registry
python manage.py seed_roles
python manage.py validate_architecture_contracts
```

Дефолт `contracts/role_rules.json` содержит
`$administration.role_assignment_allowlist` (`manager` → `customer`, `technician`).
В существующей изменённой рабочей копии блок можно добавить через защищённый
редактор либо эксплуатационную процедуру контракта. Если блока нет, делегированное
назначение закрыто; superuser сохраняет штатные возможности.

5. Configure external secret link base URL if Vaultwarden-style links are used:

```dotenv
LOCAL_BUSINESS_SECRET_VAULT_BASE_URL=https://vault.example.local
```

## Runtime Directories

Settings Center writes runtime proposals under:

```text
data/settings_center/env_proposals/
```

Runtime contract writes continue to use:

```text
data/contracts/
```

Settings Center намеренно запрещает запись в путь контракта вне
`RUNTIME_CONTRACTS_DIR`. Внешний env-override остаётся допустимым для чтения, но
для изменения через UI рабочая копия должна находиться под `data/contracts/`.
Все web-процессы должны видеть один каталог и постоянный
`.settings-contract-write.lock`.

No host-specific `.env`, certificates, credentials or deployment secrets should be committed to Git.

## Restart Semantics

`.env` changes require restart/reload of every affected process:

- Django web process;
- background worker or scheduler if present;
- AI runtime process/container if its own env changed;
- ingestion jobs started before the change.

Runtime contracts are written atomically, but long-running jobs should read fresh contracts at job start.

После аварийного завершения во время записи сначала выполните безопасную сверку:

```bash
python manage.py reconcile_settings_changes
python manage.py reconcile_settings_changes --apply
```

Первая команда ничего не меняет. Вторая завершает только однозначные состояния
по хешам before/after и никогда не переписывает контракт. `INCONSISTENT`,
`path_changed` или нечитаемый файл требуют ручного разбора до новых записей.

Если AI-действие осталось в `reconciliation_required`, сначала вручную проверьте
его предметный эффект по журналам домена, затем запишите операторское наблюдение:

```bash
python manage.py reconcile_ai_action --token <uuid> --outcome succeeded --operator <superuser-login> --reason "Эффект подтверждён по предметному журналу"
python manage.py reconcile_ai_action --token <uuid> --outcome failed --operator <superuser-login> --reason "Эффект не обнаружен; проверено оператором"
```

Перед записью используйте те же параметры с `--dry-run`. Команда не повторяет
инструмент и не закрывает `reconciliation_required`: без fencing-протокола нельзя
доказать, что прежний исполнитель остановлен. Наблюдение, оператор и причина
остаются в `AgentActionLog`; окончательное решение требует предметного разбора.

В production задайте отдельные
`LOCAL_BUSINESS_AUDIT_FINGERPRINT_KEY` и
`LOCAL_BUSINESS_AUDIT_FINGERPRINT_KEY_VERSION`. Первый используется только как
ключ HMAC для отпечатков логинов, email и AD principal в журнале; исходные
значения туда не записываются. Ключ должен быть отдельным случайным значением не
короче 32 символов; нельзя повторять `DJANGO_SECRET_KEY`. При ротации увеличьте
версию ключа.

Опредения ролей меняет активный аутентифицированный superuser или участник
роли из `$administration.role_definition_editor_roles` (по умолчанию `admin`).
`is_staff` сохраняет только вход в Django Admin; одного `manage_roles` для
редактора определений недостаточно. Стандартные access-поля User,
permissions Group и `Board.allowed_groups` в Django Admin доступны только для
чтения; резервное назначение открывается отдельной ссылкой в карточке User и
обязательно требует причину, preview и подтверждение. В карточке Board есть такой
же резервный маршрут; он использует `apps.workorders` и `BoardAccessAudit`.

## Smoke Checks

After deployment:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py access_management_e2e
python manage.py access_administration_e2e
python manage.py memory_eval --dry-run
```

Manual checks:

- `/settings/` открывается для active superuser и роли с
  `manage_settings=true`; staff-only пользователь получает 403;
- superuser can create a disabled test user and remove it or keep it disabled;
- AD link can be saved without storing AD passwords in user records;
- disabled local user cannot authenticate or restore a session through LDAP;
- superuser can open the reserve Django Admin assignment page, preview a role
  change and cancel without writing;
- superuser can preview/apply Board roles in `/settings/boards/`; техническая
  группа отклоняется, любой diff требует причину и подтверждение, резервный
  Admin-маршрут использует тот же сервис;
- superuser может отдельно изменить технические группы памяти с причиной,
  предпросмотром и доменным аудитом;
- `/settings/access/roles/` показывает каталог, а изменение одной роли сначала
  показывает серверный diff и число затронутых сотрудников;
- manager can assign only `customer`/`technician` and cannot edit own roles;
- `.env` proposal file is created under `data/settings_center/env_proposals/`;
- memory ingestion with unresolved ACL creates `acl_unresolved` issue and does not publish chunks.
