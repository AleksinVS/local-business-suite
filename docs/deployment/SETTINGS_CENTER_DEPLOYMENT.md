# Settings Center Deployment

Статус: deployment note.

Дата: 2026-05-20.

## Required Steps

1. Apply migrations:

```bash
python manage.py migrate
```

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

4. Configure external secret link base URL if Vaultwarden-style links are used:

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

## Smoke Checks

After deployment:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py memory_eval --dry-run
```

Manual checks:

- `/settings/` opens for staff/superuser and returns 403 for regular users;
- superuser can create a disabled test user and remove it or keep it disabled;
- AD link can be saved without storing AD passwords in user records;
- `.env` proposal file is created under `data/settings_center/env_proposals/`;
- memory ingestion with unresolved ACL creates `acl_unresolved` issue and does not publish chunks.
