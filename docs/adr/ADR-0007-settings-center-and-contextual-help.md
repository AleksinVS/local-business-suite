# ADR-0007: Settings Center, Contextual Help and Managed Runtime Configuration

## Status

Accepted

## Date

2026-05-20

## Context

The portal needs a user-facing GUI for configuring the AI memory system, AI/API/LLM settings, processing and extraction parameters, anonymization, access control, and user management. The same configuration UX should later be reused across all portal sections.

The project already follows a contract-driven architecture:

- Git-managed defaults live under `contracts/`;
- runtime-editable contracts live under `data/contracts/`;
- mutable runtime state lives under `data/`;
- host-specific deployment configuration, secrets, certificates and private paths do not belong in Git;
- secrets must not be stored in ordinary JSON contracts or memory artifacts;
- Django is the authority for identity, policy, audit and business state.

ADR-0003 accepted the governance-first memory architecture. ADR-0004 accepted document ingestion and graph schema bootstrapping, but deferred real source ACL inheritance and used `scope_rule` as the MVP access model. The product decision for this settings GUI changes that part: memory document access should support file-system ACL inheritance from the first GUI-oriented implementation stage.

The accepted user requirements are:

- create a new common app `apps.settings_center`;
- keep domain-specific setting descriptors close to their domain apps;
- manage portal users locally while linking them to Active Directory identities;
- use Vaultwarden-style external secret links for secrets;
- build the first GUI with Django templates and HTMX;
- support memory permissions through inherited ACLs from the file source, not only manual source-level scope rules;
- provide tooltips and AI-powered contextual mini-chat for every significant setting;
- think through required `.env` settings and how operators configure them safely.

## Decision

Implement a reusable **Settings Center** as a new Django app `apps.settings_center`.

`apps.settings_center` owns the generic configuration UX, validation orchestration, audit trail, contextual help and safe apply workflow. Domain apps own the meaning of their settings through descriptors declared near the domain code.

The architectural shape is:

```text
Domain app descriptor
  -> Settings Center registry
  -> form/schema rendering
  -> validation and dry-run checks
  -> diff/confirmation
  -> service-layer apply
  -> audit and rollback metadata
  -> contextual help mini-chat with setting_id context
```

### Descriptor Ownership

Domain descriptors are declared beside the domain that owns the setting, for example:

- `apps.memory.settings_descriptors` for memory sources, ingestion profiles, routing, graph thresholds, anonymization, ACL mapping and issue policies;
- `apps.ai.settings_descriptors` for model profiles, AI gateway/runtime settings and cloud/local routing surface;
- `apps.accounts.settings_descriptors` for local users, AD identity links and role/group mapping;
- `apps.core.settings_descriptors` for role rules, workflow rules, departments and portal-wide settings.

The Settings Center app must not become a god object. It may know how to render, validate, audit and apply a setting, but it must not embed memory, AI, account or workorder business semantics.

### Setting Descriptor Contract

Each significant setting has a stable `setting_id`, such as:

```text
memory.source.scope_rule
memory.source.acl_mode
memory.ingestion.max_file_size_mb
memory.routing.cloud_gate.max_sensitivity
accounts.user.ad_identity_link
ai.llm.default_local_model
settings_center.env.DJANGO_AUTH_MODE
```

The descriptor includes at minimum:

- domain and section;
- title, short help text and detailed help topic id;
- value type and UI widget type;
- allowed choices or schema fragment where applicable;
- storage kind: runtime contract, Django model, environment variable, secret handle, computed status or read-only deployment check;
- write policy: editable, proposed change only, read-only, secret-handle-only;
- required permission/capability;
- sensitivity and masking rules;
- validation function and optional dry-run command;
- whether change requires restart, background job restart, reindexing or contract sync;
- audit category and rollback behavior.

### Runtime Contracts

Settings backed by runtime contracts are edited through service functions that:

1. load the current runtime copy from `data/contracts/`;
2. apply a typed patch through JSON pointer or a domain-specific editor;
3. validate the full payload using the existing validators;
4. run cross-contract validation where needed;
5. write atomically with `.tmp` + `os.replace`;
6. refresh in-process settings or mark restart/reload as required;
7. create a settings audit event with before/after hashes and actor.

The GUI must not edit default contracts in `contracts/` during production operation.

### `.env` Settings

Environment variables remain deployment-specific configuration. The Settings Center may display and validate their effective values, but production defaults to **proposal mode**, not direct `.env` mutation.

Accepted apply modes:

- `read_only`: display effective values and required status only;
- `proposal`: generate an operator-reviewed `.env` change proposal under runtime data;
- `local_file`: atomically edit a configured `.env` file, allowed only for development or explicitly trusted single-host deployments.

Production default is `proposal`.

Most `.env` changes require process restart because Django settings are loaded at process startup. The GUI must make this explicit and provide a restart checklist/status, not pretend that every value can hot-reload.

### Secrets

Secrets are configured through secret handles, not raw values.

The MVP secret provider is a Vaultwarden-style external link backend. The Settings Center can create/display a `SecretHandle`, label, provider and external URL. It must not store API keys, passwords, private keys or tokens in ordinary settings audit payloads, runtime contracts, help prompts or logs.

### User Management And AD Link

Portal users are managed locally in Django:

- create user;
- disable user;
- update local profile and department;
- assign local groups/roles;
- mark staff/superuser according to server-side permissions.

Active Directory is linked as an external identity source, not as the authority that overwrites all local user management. The implementation should add an explicit AD identity link model or equivalent normalized structure rather than overloading role/group fields.

Recommended identity link attributes:

- provider: `active_directory`;
- AD SID where available;
- `sAMAccountName`;
- UPN;
- distinguished name;
- domain;
- last sync timestamp;
- sync status and error;
- raw AD attributes allowlist only.

AD group data may be used for ACL resolution and optional role suggestions. Automatic role overwrite from AD must be explicitly enabled and auditable.

### Memory ACL Inheritance

This ADR amends ADR-0004 in the ACL area.

Memory ingestion should include source ACL inheritance in the first Settings Center implementation stage. Source-level `scope_rule` remains useful as a fallback and for synthetic/internal sources, but file-based corporate document sources should support inherited ACLs.

The ACL pipeline is:

```text
local/UNC source object
  -> read file ACL metadata under service account
  -> normalize principals to AD/user/group keys
  -> resolve known principals to portal users/groups/scope tokens
  -> apply deny/unknown-principal policy conservatively
  -> attach scope tokens to snapshots/chunks/facts
  -> repeat scope filtering at retrieval
  -> audit decisions and unresolved ACL issues
```

If ACL metadata cannot be read or resolved, the default policy is fail-closed: create a visible issue and do not publish chunks to ordinary users until the ACL problem is resolved.

### Contextual Help And Mini-Chat

Every significant setting should expose:

- a normal hover tooltip;
- a help icon;
- a floating mini-chat opened with the current `setting_id` context.

When opened, the mini-chat immediately displays the help topic for that setting. User questions sent from the mini-chat include structured context:

- `setting_id`;
- domain and section;
- setting descriptor metadata;
- non-secret current value summary;
- allowed options;
- relevant contract/schema fragment;
- linked internal documentation ids.

The bot must know which setting the user is asking about without relying on the user restating it. The bot may explain and propose changes, but write operations must go through the normal diff/confirmation/service-layer path.

## Alternatives Considered

### Extend Django Admin only

Rejected as the main architecture. Django Admin is useful for low-volume operator inspection, but it is not a good long-term base for reusable contextual help, guided validation, settings diffs, domain descriptors and user-friendly memory configuration.

### Build a separate SPA admin from the start

Deferred. A SPA could provide a richer UX, but the existing project is Django-template oriented and already includes HTMX. Starting with Django templates/HTMX reduces implementation and deployment complexity while preserving the option to add a richer frontend later.

### Put all setting logic in `apps.core`

Rejected. `apps.core` already holds shared utilities and policy/config helpers, but a reusable cross-domain settings system deserves a clear boundary. A dedicated `apps.settings_center` avoids expanding `apps.core` into an operational god app.

### Store `.env` and secrets in runtime contracts

Rejected. `.env` is deployment-specific, and secrets must not be persisted as ordinary config. Runtime contracts can reference secret handles and deployment profiles, but they must not contain raw secret values.

### Keep ACL inheritance deferred

Rejected by the new product decision. The first GUI-oriented memory settings implementation should support inherited ACLs for file sources, with conservative failure behavior.

## Consequences

### Positive

- Provides one consistent settings UX for memory, AI, users, roles and later portal modules.
- Keeps domain ownership clear through descriptors beside domain code.
- Preserves contract-driven configuration and atomic runtime writes.
- Gives operators inline explanations and AI help without exposing secrets.
- Makes configuration changes auditable and reviewable.
- Treats `.env` and secrets according to deployment/security boundaries.
- Moves memory access toward real source ACLs instead of only source-level scope rules.

### Negative

- More implementation work than simple per-page forms.
- Requires a descriptor registry and careful permission model.
- ACL inheritance increases Windows/AD deployment complexity.
- `.env` settings cannot all be applied live; operators need restart/reload workflows.
- Contextual AI help must be bounded to avoid leaking sensitive settings or creating unauthorized changes.

## Required Follow-up

- Create the Settings Center implementation plan.
- Add `apps.settings_center` with registry, descriptor model, audit model, forms/views and HTMX templates.
- Add descriptor modules in `apps.memory`, `apps.ai`, `apps.accounts` and `apps.core`.
- Add settings audit and rollback metadata.
- Add contextual help topics and mini-chat service integration.
- Add local user management with explicit AD identity links.
- Add memory ACL resolver, ACL mapping settings, unresolved ACL issue visibility and tests.
- Add `.env` status/proposal workflow and deployment documentation.
- Update `.env.example` only when corresponding settings are implemented in code.
