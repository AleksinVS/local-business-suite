# Active Plan: Settings Center GUI

## Status

Implemented; owner review pending.

## Context

The project needs a reusable GUI for memory, AI/LLM, processing, anonymization, ACL, user management and contextual help settings.

Accepted architecture:

- `apps.settings_center` owns common settings UI, registry, validation orchestration, audit and contextual help.
- Domain descriptors are declared beside their domain apps.
- First GUI uses Django templates and HTMX.
- Users are managed locally and linked to AD identities.
- Secrets use Vaultwarden-style external links.
- Memory file-source permissions should inherit source ACLs from the first GUI implementation stage.

References:

- `docs/adr/ADR-0007-settings-center-and-contextual-help.md`;
- `docs/architecture/SETTINGS_CENTER_IMPLEMENTATION_PLAN.md`;
- `workflow/active/settings-center-gui/`;
- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`.

## Scope

- Create `apps.settings_center`.
- Add descriptor registry and domain descriptor modules.
- Add Settings Center dashboard and HTMX forms.
- Add runtime contract edit/apply/audit flow.
- Add contextual tooltip/help/mini-chat mechanism.
- Add local user management and AD identity link.
- Add memory ACL inheritance configuration and resolver path.
- Add `.env` status/proposal workflow.

## Non-goals

- Do not build a separate SPA in the first version.
- Do not store raw secret values in runtime contracts, audit events or help prompts.
- Do not turn Settings Center into the owner of memory/account/AI business logic.
- Do not implement production service-resolved secrets before a separate decision.
- Do not expose raw document paths or sensitive ACL details to unauthorized users.

## Read Scope

- `apps.core`;
- `apps.accounts`;
- `apps.ai`;
- `apps.memory`;
- `contracts/`;
- `config/settings.py`;
- `templates/`;
- `docs/adr/`;
- `docs/architecture/`;
- `docs/deployment/`;
- `docs/guides/`.

## Write Scope

Expected implementation write scope:

- `apps/settings_center/`;
- descriptor modules under relevant apps;
- selected templates/static files;
- tests for settings center, memory ACL and account AD-link behavior;
- docs and `.desc.json` files;
- `PROJECT_STRUCTURE.yaml` through `make gen-struct`.

## Acceptance Checks

- Settings Center lists descriptors from at least core, accounts, AI and memory.
- Runtime contract changes validate and apply atomically.
- Settings changes create audit events with masked diffs.
- `.env` settings use proposal/read-only mode in production.
- Secret settings use handles only.
- Local users can be created, disabled and linked to AD identity.
- ACL inheritance fail-closed behavior is tested.
- Context mini-chat opens with `setting_id` and safe descriptor context.
- Documentation and project structure are updated.

## Execution Package

Workflow block:

```text
workflow/active/settings-center-gui/
```

Task packets:

- `01-settings-center-foundation`;
- `02-runtime-contract-settings`;
- `03-user-management-ad-link`;
- `04-memory-acl-inheritance`;
- `05-contextual-help-minichat`;
- `06-env-status-proposals`.

## Verification Commands

```bash
python manage.py check
python manage.py validate_architecture_contracts
python manage.py test apps.settings_center.tests apps.memory.tests apps.accounts.tests apps.ai.tests
make gen-struct
```

## Implementation Result

Implemented on 2026-05-20:

- `apps.settings_center` with descriptor registry, dashboard, runtime contract editor, audit, env proposals and contextual help mini-chat.
- Domain descriptors in `apps.core`, `apps.accounts`, `apps.ai` and `apps.memory`.
- Local user management and explicit `ExternalIdentity` AD link.
- Memory ACL inheritance MVP with fail-closed unresolved ACL issue behavior.
- Operational and deployment docs for Settings Center.

Actual verification is recorded in `workflow/active/settings-center-gui/HANDOFF_REPORT.md`.
