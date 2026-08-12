# Settings Center Deployment

Статус: deployment note.

Дата: 2026-05-20.

## Required Steps

1. Apply migrations:

```bash
python manage.py migrate
```

Миграция `accounts.0010_accessassignmentaudit_source_and_context` добавляет источник,
причину, correlation id и одноразовый отпечаток предпросмотра.

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

No host-specific `.env`, certificates, credentials or deployment secrets should be committed to Git.

## Restart Semantics

`.env` changes require restart/reload of every affected process:

- Django web process;
- background worker or scheduler if present;
- AI runtime process/container if its own env changed;
- ingestion jobs started before the change.

Runtime contracts are written atomically, but long-running jobs should read fresh contracts at job start.

Определения ролей меняет только активный superuser. Стандартные access-поля User,
permissions Group и `Board.allowed_groups` в Django Admin доступны только для
чтения; резервное назначение открывается отдельной ссылкой в карточке User и
обязательно требует причину, preview и подтверждение.

## Smoke Checks

After deployment:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py access_management_e2e
python manage.py memory_eval --dry-run
```

Manual checks:

- `/settings/` opens for staff/superuser and returns 403 for regular users;
- superuser can create a disabled test user and remove it or keep it disabled;
- AD link can be saved without storing AD passwords in user records;
- disabled local user cannot authenticate or restore a session through LDAP;
- superuser can open the reserve Django Admin assignment page, preview a role
  change and cancel without writing;
- manager can assign only `customer`/`technician` and cannot edit own roles;
- `.env` proposal file is created under `data/settings_center/env_proposals/`;
- memory ingestion with unresolved ACL creates `acl_unresolved` issue and does not publish chunks.
