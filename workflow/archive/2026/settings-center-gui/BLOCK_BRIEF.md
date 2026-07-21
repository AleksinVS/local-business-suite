# Workflow brief: Settings Center GUI

## Goal

Create the implementation path for a reusable Settings Center that configures portal runtime contracts, AI/LLM settings, memory ingestion and ACL behavior, users, access, `.env` status/proposals and contextual AI help.

## Business Value

Operators should configure the portal through governed GUI flows instead of editing JSON, `.env` and admin records manually. Every significant setting should be understandable through tooltip/help and auditable when changed.

## Method Note

Settings are not one technical category. Runtime contracts can be patched and validated while the app is running. Django model state must change through services and audit. `.env` values are deployment bootstrap settings and usually require restart. Secrets must be represented by handles, not raw values. The workflow therefore builds a governed apply path, not a generic file editor.

## Architecture Sources

- `docs/adr/ADR-0007-settings-center-and-contextual-help.md`;
- `docs/architecture/SETTINGS_CENTER_IMPLEMENTATION_PLAN.md`;
- `docs/planning/active/settings-center-gui.md`;
- `docs/adr/ADR-0003-ai-memory-service.md`;
- `docs/adr/ADR-0004-memory-ingestion-and-graph-schema-bootstrapping.md`;
- `docs/adr/ADR-0005-chat-derived-memory-and-secret-handles.md`;
- `docs/architecture/MEMORY_INGESTION_BOOTSTRAPPING_PLAN.md`;
- `docs/architecture/MEMORY_CHAT_REFLECTION_AND_SECRET_HANDLES_PLAN.md`.

## Read Scope

- `apps/core/`;
- `apps/accounts/`;
- `apps/ai/`;
- `apps/memory/`;
- `config/settings.py`;
- `contracts/`;
- `templates/`;
- `static/`;
- `docs/adr/`;
- `docs/architecture/`;
- `docs/deployment/`;
- `docs/guides/`;
- `docs/planning/active/settings-center-gui.md`;
- `workflow/active/settings-center-gui/`.

## Write Scope For Future Implementation

Future implementation task packets may write:

- `apps/settings_center/`;
- descriptor modules under `apps/core/`, `apps/accounts/`, `apps/ai/`, `apps/memory/`;
- migrations for settings audit and AD identity link where needed;
- selected templates/static files for Django templates + HTMX;
- tests under relevant apps;
- docs, deployment guides and `.desc.json`;
- `PROJECT_STRUCTURE.yaml` after `make gen-struct`.

Runtime/generated artifacts belong under `data/` or `.local/` only. Secrets and host-specific deployment values must not be committed.

## Non-goals

- No separate SPA in the first implementation slice.
- No raw secret storage in contracts, `.env` proposals, audit payloads, help prompts or logs.
- No direct editing of Git-managed default contracts through production GUI.
- No bypass of domain services and policy checks.
- No automatic overwrite of local portal roles from AD unless a later explicit sync policy enables it.
- No publishing of memory chunks when source ACL cannot be resolved, unless an explicitly reviewed fallback policy is implemented.

## Acceptance

- `apps.settings_center` registers descriptors from core, accounts, AI and memory.
- Staff/admin users can open a Settings Center dashboard built with Django templates and HTMX.
- Runtime contract settings validate, show masked diffs, apply atomically and create audit events.
- User management supports local create/disable/profile/role changes and explicit AD identity link.
- Memory file-source ACL inheritance is implemented fail-closed for unresolved ACLs.
- Significant settings expose tooltip and contextual mini-chat with stable `setting_id`.
- `.env` settings are shown as effective status and proposal workflow, not silently edited in production.
- Verification and operations documentation is updated.
