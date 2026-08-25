# Executor Report — 03: Single role administration authority

## Result

Implemented the ADR-0043 role administration model. `manage_roles` is now the
only product authority for ordinary role creation, editing, membership changes,
and assignment. Active superusers retain the complete reserve path, including
self-assignment and the audited Django Admin adapter.

## Main changes

- Removed runtime authorization reads of
  `$administration.role_definition_editor_roles` and
  `$administration.role_assignment_allowlist`.
- Added strict ordinary/protected classification. Protection is evaluated from
  both the current and proposed role using explicit `protected=true` and the
  code-owned `PROTECTED_CAPABILITIES` set. Malformed protected grants fail
  closed.
- Kept non-superuser self-assignment and held-role-definition changes denied.
- Added least-privilege role creation with reserved-code and existing
  technical/AD/memory group collision checks, constrained contract transport,
  fresh under-lock authority checks, atomic contract audit, and idempotent
  Group/GroupProfile materialization.
- Kept role deletion unavailable through raw apply, rollback, and the
  constrained writer.
- Added a dedicated active-superuser deployment command that removes only the
  inert legacy `$administration` block using expected hashes, backup, staged
  audit, and atomic replacement.
- Added a minimal standalone create form; unified-drawer integration remains in
  task 06.
- Updated the contract default/schema, seed repair behavior, user/operations/
  deployment guides, and the current policy-model document.

## Review corrections during implementation

The primary review caught and corrected these issues before acceptance:

- `manage_roles` initially re-read a global contract instead of using the
  under-lock snapshot;
- role materialization initially occurred outside the access lock and could
  reclassify a colliding technical group;
- the idempotent repair path initially lacked a fresh actor check;
- non-superusers initially saw a protected-role checkbox they could not use;
- trusted `seed_roles` repair initially rejected an existing authoritative role
  group without a profile;
- the creation template initially omitted the role code field;
- the reserved code `viewer` was added to prevent collision with task 04.

## Verification

Primary focused authority matrix:

```text
25 passed, 372 deselected, 26 subtests passed
```

Full affected modules:

```text
387 passed, 10 deselected, 90 subtests passed
```

Final creation/migration regression:

```text
6 passed, 113 deselected, 10 subtests passed
```

`python manage.py validate_architecture_contracts`, Django system check, and
`git diff --check` passed.

## Runtime operation

The primary agent ran `migrate_role_administration` through the canonical
deployment service as local active superuser `abc`. `SettingsChange` audit ID 8
records the change; the runtime block was removed atomically and the verified
backup is under `data/contracts/backups/`. Runtime data remains ignored by Git.

## Residual scope

- The default/runtime role contract differs intentionally: existing business
  role values remain runtime-owned, while protection is effective even when an
  older role has no explicit `protected` field.
- The explicit `viewer` role, removal of the roleless fallback, and Board ACL
  migration belong to task 04.
- The current one-window create/editor presentation and browser e2e belong to
  task 06.
