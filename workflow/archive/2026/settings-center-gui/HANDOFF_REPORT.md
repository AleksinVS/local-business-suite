# Handoff Report: Settings Center GUI

## Status

Implemented; owner review pending.

## Slice Checklist

- [x] `01-settings-center-foundation`: app, registry, dashboard, permissions, audit skeleton.
- [x] `02-runtime-contract-settings`: contract read/validate/diff/apply via runtime contract files.
- [x] `03-user-management-ad-link`: local user create/update/disable and explicit AD identity link.
- [x] `04-memory-acl-inheritance`: inherited ACL metadata mapping and fail-closed `acl_unresolved` path.
- [x] `05-contextual-help-minichat`: descriptor tooltip/help context and HTMX floating mini-chat.
- [x] `06-env-status-proposals`: masked effective env status and proposal files under `data/`.

## Implementation Summary

- Added `apps.settings_center` with descriptors, registry, views, forms, audit models, env proposal models and tests.
- Added domain descriptors under `apps.core`, `apps.accounts`, `apps.ai` and `apps.memory`.
- Added `ExternalIdentity` model and services for AD link metadata beside local users.
- Added memory ACL resolver MVP in `apps.memory.acl` and integrated it into document ingestion.
- Extended memory ingestion profile validation/default contracts for `inherit_source_acl`.
- Added Settings Center templates for dashboard, contract editor, users, AD link, env status/proposals and contextual help.
- Added operations/deployment docs and updated `.desc.json` metadata.

## Verification

```bash
.venv/bin/python manage.py check
# passed

.venv/bin/python manage.py validate_architecture_contracts
# passed

.venv/bin/python manage.py makemigrations --check --dry-run
# passed, no changes detected

.venv/bin/python manage.py test apps.settings_center.tests apps.accounts.tests apps.memory.tests apps.ai.tests
# passed, 105 tests

.venv/bin/python manage.py memory_eval --dry-run
# passed, 4 checks
```

```bash
make gen-struct
# passed, PROJECT_STRUCTURE.yaml regenerated
```

```bash
git diff --check -- . ':(exclude)BACKLOG.md'
# passed
```

Full `git diff --check` is blocked by pre-existing trailing whitespace in root `BACKLOG.md`, outside this workflow's write scope.

## Runtime E2E

After owner request, runtime migrations were applied and local services were restarted:

```bash
.venv/bin/python manage.py migrate
# applied accounts.0004_externalidentity and settings_center.0001_initial
```

Restarted:

- gunicorn on `0.0.0.0:8001`;
- agent runtime on `127.0.0.1:8090`.

HTTP E2E against real gunicorn passed:

- login through `/accounts/login/`;
- `/settings/` dashboard;
- descriptor help panel and `help_ask` mini-chat route;
- `.env` proposal creation;
- user create;
- AD identity link;
- user disable;
- cleanup of temporary E2E users/proposal files.

## Files Changed

Main implementation areas:

- `apps/settings_center/`
- `templates/settings_center/`
- `apps/accounts/models.py`, `apps/accounts/services.py`, `apps/accounts/settings_descriptors.py`
- `apps/core/settings_descriptors.py`
- `apps/ai/settings_descriptors.py`
- `apps/memory/acl.py`, `apps/memory/settings_descriptors.py`, `apps/memory/document_ingestion.py`
- `contracts/ai/memory_ingestion_profiles.json`
- `contracts/schemas/memory_ingestion_profiles.schema.json`
- `docs/guides/SETTINGS_CENTER_OPERATIONS.md`
- `docs/deployment/SETTINGS_CENTER_DEPLOYMENT.md`

## Remaining Risks

- Native Windows ACL collection for real UNC/local file ACLs is not implemented yet; the MVP consumes normalized ACL metadata/overrides and fails closed otherwise.
- Contextual help uses safe local descriptor-aware responses. Production LLM routing should be added with a trusted model profile and explicit audit.
- Runtime contract editor is JSON-first; high-traffic operator settings should get typed field-level forms in later slices.
