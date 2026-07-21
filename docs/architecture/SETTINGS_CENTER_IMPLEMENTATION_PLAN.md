# План: Settings Center, GUI настроек и контекстная справка

Статус: архитектурный план; реализация не начата.

Дата: 2026-05-20.

Связанный ADR: `docs/adr/ADR-0007-settings-center-and-contextual-help.md`.

## Назначение

Этот документ описывает реализацию общего GUI для настройки портала, памяти, AI/LLM, обработки документов, анонимизации, прав доступа и пользователей. Первый UI строится на Django templates и HTMX. Общий слой находится в новом приложении `apps.settings_center`, а доменные descriptors объявляются рядом с соответствующими доменами.

## Методическая заметка

Настройки production-системы делятся на несколько классов:

- runtime contracts можно менять через UI атомарно и валидировать сразу;
- Django model state меняется через сервисы, формы и audit;
- `.env` обычно читается при старте процесса, поэтому изменение требует restart/reload;
- секреты не должны быть значениями настроек, они должны быть ссылками на controlled secret backend.

Поэтому Settings Center должен быть не "редактором JSON и `.env`", а управляемым контуром: descriptor -> форма -> валидация -> diff -> подтверждение -> сервисное применение -> audit -> проверка результата.

## Принятые решения

- Новый общий app: `apps.settings_center`.
- Доменные descriptors живут рядом с доменами:
  - `apps.memory.settings_descriptors`;
  - `apps.ai.settings_descriptors`;
  - `apps.accounts.settings_descriptors`;
  - `apps.core.settings_descriptors`.
- Пользователи портала управляются локально.
- Active Directory используется как связанная external identity и источник ACL/group metadata.
- Секреты на первом этапе идут через Vaultwarden-style external secret links.
- Первый GUI делается на Django templates + HTMX.
- Права памяти для файловых источников сразу проектируются с наследованием ACL из источника.
- `.env` в production настраивается через status/proposal workflow, а не через скрытую запись секретов в runtime contracts.

## Пояснение про single-host, single-process и workers

Вопрос "single-host/single-process или несколько workers/containers" нужен не для выбора UX, а для корректного применения настроек.

Разные варианты:

- **Single-host**: все компоненты работают на одном сервере. Это может быть один процесс или несколько процессов на одном host.
- **Single-process**: один Django process обслуживает web-запросы. Если он изменил in-memory settings, других процессов нет.
- **Several workers**: Gunicorn/uWSGI/Daphne или background workers запускают несколько процессов. Каждый процесс уже загрузил `settings.py` и может не увидеть изменение `.env` или runtime-файла без reload/cache invalidation.
- **Several containers**: web, worker, scheduler, AI runtime и parser/OCR service могут быть отдельными контейнерами. Изменение `.env` одного контейнера не меняет остальные автоматически.

Для текущего проекта разумное допущение: **single host, but not single process**. Даже на одном сервере могут быть web worker, management commands, ingestion jobs и AI runtime. Поэтому архитектура должна:

- считать `.env` restart-required;
- не полагаться на изменение `django.conf.settings` как на полноценный runtime reload;
- писать runtime contracts атомарно;
- иметь settings version/audit;
- показывать, какие процессы или jobs нужно перезапустить;
- для background jobs читать свежие runtime contracts при старте job или через явный config loader.

## Компоненты `apps.settings_center`

### Descriptor Registry

Регистрирует descriptors от доменных apps.

Минимальная структура descriptor:

```text
setting_id
domain
section
title
description
help_topic_id
storage_kind
value_type
widget
choices/schema
read_adapter
write_adapter
validator
dry_run_check
required_permission
sensitivity
masking_policy
requires_restart
requires_reindex
audit_category
```

Storage kinds:

- `runtime_contract`;
- `django_model`;
- `env_var`;
- `secret_handle`;
- `computed_status`;
- `read_only_external`.

Write policies:

- `editable`;
- `proposal_only`;
- `read_only`;
- `secret_handle_only`;
- `requires_domain_workflow`.

### Apply Service

Единый service-layer контур:

```text
read current value
  -> validate candidate
  -> render diff
  -> require confirmation
  -> apply through domain adapter
  -> run post-apply validation
  -> write audit event
  -> return reload/restart/reindex instructions
```

Для runtime contracts использовать существующие validators из `apps.core.json_utils` и атомарную запись через `.tmp` + `os.replace`.

### Audit Models

Предварительные модели:

- `SettingsChange`
  - actor;
  - setting_id;
  - domain;
  - storage_kind;
  - action;
  - status;
  - before_hash;
  - after_hash;
  - masked_diff;
  - validation_result;
  - requires_restart;
  - created_at/applied_at.
- `SettingsChangeComment`
  - change;
  - actor;
  - comment.
- `SettingsEnvProposal`
  - generated `.env` proposal metadata;
  - target host/profile label;
  - masked key/value changes;
  - status.

Сырые секретные значения в audit запрещены.

### UI

Первый UI:

- settings dashboard по доменам;
- memory setup wizard;
- AI/LLM setup;
- users and access;
- `.env` status/proposals;
- validation results;
- issue panels for memory ingestion/ACL/config problems;
- floating help mini-chat.

HTMX использовать для:

- field-level validation;
- test connection;
- dry-run;
- diff preview;
- help mini-chat panel;
- reload/restart status refresh.

## Доменные настройки памяти

### Memory Sources

Настройки:

- source code/title/domain/owner;
- source kind: local path, UNC path, external connector, contract docs, synthetic;
- source ref with masking for sensitive host paths;
- enabled/disabled;
- sensitivity;
- PII policy;
- retention policy;
- extractor/chunking/index profiles;
- ignore patterns;
- schedule/sync mode.

Проверки:

- JSON contract valid;
- source path reachable under service identity where possible;
- no mapped drives for Windows services;
- source sensitivity compatible with routing;
- source has access mode configured.

### Processing And Extraction

Настройки:

- parser profile;
- OCR backend/languages;
- file size limit;
- parser/OCR timeouts;
- raw mode;
- partial indexing policy;
- issue policy;
- graph confidence thresholds;
- auto-accept/review policy.

Проверки:

- dry-run parser availability;
- OCR backend status;
- limit sanity;
- cloud mode denied for sensitive documents unless prepared package policy allows it.

### ACL Inheritance

Новый first-stage contour:

```text
file ACL
  -> raw principal/SID extraction
  -> AD identity/group resolution
  -> portal user/group/scope token mapping
  -> snapshot/chunk/fact scope tokens
  -> retrieval double-filtering
```

Нужные настройки:

- source ACL mode: `scope_rule`, `inherit_source_acl`, `inherit_source_acl_with_fallback`;
- unresolved ACL policy: `block`, `admin_only`, `fallback_scope_rule`;
- principal mapping profile;
- AD group nesting depth;
- ACL cache TTL;
- service account ACL read test;
- issue severity for unresolved ACLs.

Рекомендуемый default:

```text
acl_mode = inherit_source_acl
unresolved_acl_policy = block
acl_fail_closed = true
```

Если ACL не прочитан или principal неизвестен, документ не должен становиться доступным обычным пользователям. Создается visible issue.

## Пользователи и AD link

Локальное управление:

- create user;
- disable user;
- update full name/email/department;
- set local password or require password reset;
- assign local groups;
- mark staff/superuser only by superuser;
- audit all privilege changes.

AD link:

- link local user to AD identity by SID/UPN/sAMAccountName;
- validate link through LDAP lookup;
- store allowlisted AD attributes only;
- show AD sync status;
- use AD group/SID data for ACL resolution;
- do not overwrite local groups unless an explicit sync policy is enabled.

Recommended model:

```text
ExternalIdentity
  user
  provider = active_directory
  subject_id = SID
  username = sAMAccountName
  upn
  distinguished_name
  domain
  attributes
  last_synced_at
  sync_status
```

## Contextual Help And AI Mini-Chat

Для каждого значимого пункта:

- tooltip: краткая справка;
- help icon: открывает floating mini-chat;
- mini-chat сразу показывает help topic;
- каждый вопрос отправляется с `setting_id` и descriptor context.

Контекст mini-chat:

```json
{
  "setting_id": "memory.source.acl_mode",
  "domain": "memory",
  "section": "Access",
  "title": "ACL mode",
  "allowed_values": ["scope_rule", "inherit_source_acl"],
  "current_value_summary": "inherit_source_acl",
  "sensitivity": "internal",
  "docs": [
    "ADR-0007",
    "MEMORY_INGESTION_BOOTSTRAPPING_PLAN"
  ]
}
```

Запрещено передавать:

- raw secrets;
- full service account passwords;
- private keys;
- raw patient data;
- unmasked sensitive paths unless actor has permission and the help provider is local/trusted.

## `.env` Governance

### Почему `.env` не равен runtime settings

`.env` содержит host-specific bootstrap settings. Большинство значений читается при старте Django или worker process. UI может помочь настроить `.env`, но не должен обещать мгновенное применение без restart.

### Apply modes

Рекомендуемые режимы Settings Center:

```text
SETTINGS_CENTER_ENV_APPLY_MODE=proposal
```

Варианты:

- `read_only`: только статус и подсказки;
- `proposal`: создать операторское предложение изменения;
- `local_file`: писать `.env` атомарно, только для dev/trusted single-host.

Production default: `proposal`.

### Proposed settings-center env keys

Эти ключи нужно добавлять в `.env.example` только при реализации соответствующего кода:

```dotenv
SETTINGS_CENTER_ENABLED=true
SETTINGS_CENTER_ENV_APPLY_MODE=proposal
SETTINGS_CENTER_ENV_FILE=.env
SETTINGS_CENTER_ENV_PROPOSAL_DIR=data/settings_center/env_proposals
SETTINGS_CENTER_HELP_AI_ENABLED=true
SETTINGS_CENTER_HELP_MODEL_PROFILE=local_admin_help_v1
SETTINGS_CENTER_HELP_MAX_CONTEXT_CHARS=6000
SETTINGS_CENTER_AUDIT_RETENTION_DAYS=365
```

### Existing core/security env keys

Уже используются:

```dotenv
DJANGO_ENV=production
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=...
DJANGO_ALLOWED_HOSTS=portal.example.local
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
APP_DISPLAY_NAME=...
```

### Auth and AD env keys

Если пользователи управляются локально, но нужна AD-связь для ACL, рекомендуемая модель:

```dotenv
DJANGO_AUTH_MODE=local
AD_LDAP_TRANSPORT=ldaps
AD_LDAP_VERIFY_CERT=true
AD_LDAP_HOST=dc01.example.local
AD_LDAP_PORT=636
AD_LDAP_DOMAIN=EXAMPLE
AD_SEARCH_DN=DC=example,DC=local
AD_SERVICE_ACCOUNT=EXAMPLE\svc_portal_lookup
AD_SERVICE_PASSWORD=...
AD_LDAP_USER_FILTER=(sAMAccountName={username})
AD_LDAP_CA_FILE=C:\path\to\ca.pem
```

Если нужно одновременно разрешить AD login, использовать `DJANGO_AUTH_MODE=hybrid`, но автоматическое перетирание локальных ролей должно быть отдельной настройкой и audit event.

Планируемые ключи для будущей реализации AD-link политики:

```dotenv
ACCOUNTS_AD_LINK_ENABLED=true
ACCOUNTS_AD_LINK_MODE=manual
ACCOUNTS_AD_GROUP_ROLE_SYNC=false
```

### Secret vault env keys

Vaultwarden-style MVP:

```dotenv
LOCAL_BUSINESS_SECRET_VAULT_BASE_URL=https://vault.example.local
```

Raw vault tokens не нужны для external-link MVP. Если позже появится service-resolved secret backend, это будет отдельное ADR/plan.

### AI and mini-chat env keys

Уже используются AI runtime settings:

```dotenv
LOCAL_BUSINESS_AI_GATEWAY_TOKEN=...
LOCAL_BUSINESS_AGENT_RUNTIME_URL=http://127.0.0.1:8090
LOCAL_BUSINESS_AGENT_RUNTIME_TIMEOUT=90
DJANGO_AI_GATEWAY_URL=http://127.0.0.1:8000/ai/gateway
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
AI_AGENT_MODEL=openai:gpt-4.1-mini
AI_AGENT_MODEL_NAME=gpt-4.1-mini
```

Для admin help предпочтителен local/trusted profile. Cloud help по чувствительным настройкам должен быть запрещен или получать только masked context.

### Memory ACL and ingestion env keys

Планируемые ключи для реализации ACL inheritance:

```dotenv
MEMORY_ACL_INHERITANCE_ENABLED=true
MEMORY_ACL_FAIL_CLOSED=true
MEMORY_ACL_UNRESOLVED_POLICY=block
MEMORY_ACL_GROUP_NESTING_DEPTH=5
MEMORY_ACL_CACHE_TTL_SECONDS=3600
```

Parser/OCR settings после подключения production parser/OCR:

```dotenv
MEMORY_DOCLING_ENABLED=true
MEMORY_TIKA_URL=
MEMORY_LIBREOFFICE_PATH=
MEMORY_OCR_BACKEND=tesseract
MEMORY_TESSERACT_CMD=tesseract
MEMORY_OCR_LANGUAGES=rus+eng
```

### Queue and worker env keys

Существующие:

```dotenv
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_BACKEND=sqlite
LOCAL_BUSINESS_EXTERNAL_CONNECTOR_QUEUE_PATH=data/memory/queues/external_connectors.sqlite3
GUNICORN_TIMEOUT=600
GUNICORN_GRACEFUL_TIMEOUT=30
```

Если появятся background workers для settings/help/ACL/parser jobs, их env надо оформлять рядом с implementation task, не заранее.

## Реализация по этапам

### Phase 1. ADR, plan and descriptor skeleton

- Add `apps.settings_center`.
- Add descriptor dataclasses/registry.
- Add no-op descriptors for core domains.
- Add settings dashboard route behind staff/role permission.
- Add tests for registry loading.

### Phase 2. Runtime contract editor

- Implement runtime contract read/patch/validate/apply service.
- Support memory sources/profiles/routing/ingestion contracts first.
- Add diff and confirmation UI.
- Add audit model.
- Add rollback-by-previous-payload workflow for low-risk contract edits.

### Phase 3. User management and AD link

- Add local user management screens.
- Add AD identity link model/service.
- Add LDAP lookup/test action.
- Add audit for role, staff/superuser and AD-link changes.

### Phase 4. Memory ACL inheritance

- Add ACL resolver interface.
- Add Windows/local/UNC ACL collector adapter.
- Add principal mapping and AD group expansion.
- Add unresolved ACL issues.
- Store derived scope tokens on source objects/snapshots/chunks/facts.
- Add tests for fail-closed behavior.

### Phase 5. Context help and mini-chat

- Add help topic registry.
- Add tooltip rendering helper.
- Add floating HTMX mini-chat.
- Route help requests through AI gateway with masked setting context.
- Add tests that secret fields are not included in help context.

### Phase 6. `.env` status and proposals

- Add env descriptors.
- Add effective value display with masking.
- Add validation/test actions.
- Add proposal generation under `data/settings_center/env_proposals/`.
- Add restart-required status and operator checklist.

## Acceptance Checks

- A staff/admin user can open Settings Center and see registered domain sections.
- Runtime memory contract changes show diff, validate, apply atomically and create audit.
- Invalid contract edits are rejected before write.
- Secret settings accept only secret handles or external vault links.
- `.env` values are masked and marked restart-required where appropriate.
- Production mode does not silently write `.env` unless explicitly configured.
- Local users can be created/disabled and linked to AD identities.
- ACL inheritance fail-closed tests pass for unresolved principals.
- Context help receives `setting_id` and safe descriptor context.
- Mini-chat cannot receive raw secrets.

## Verification Commands

Expected implementation checks:

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.settings_center.tests apps.memory.tests apps.accounts.tests apps.ai.tests
python manage.py memory_eval --dry-run
```

If project structure changes, update relevant `.desc.json` files and run:

```bash
make gen-struct
```
