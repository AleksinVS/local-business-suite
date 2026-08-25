# Task Acceptance — 01: Frozen capability metadata

## Verdict

PASS.

The primary agent reviewed the implementation and accepts the package for the
feature branch. It is not yet the final block acceptance and has not been pushed
or merged.

## Accepted invariants

- Every ordinary `role_rules` write runs under the common access lock and
  requires the runtime `$capabilities` catalog to match the immutable Git
  default.
- Ordinary apply, constrained role save, and rollback cannot change
  `$capabilities`.
- The deployment-only migration reloads an active superuser under the lock,
  checks the runtime-catalog, Git-catalog, and full-runtime hashes, validates a
  complete candidate, rejects unrelated deltas, creates a verified backup and
  uses the existing staged audit and atomic-write protocol.
- Invalid, stale, drifted, no-op, or unrelated candidates fail before a
  successful audit or runtime replacement.

## Primary-agent verification

```text
make verify-fast \
  TEST_SCOPE="apps/settings_center/tests.py apps/accounts/tests.py" \
  TEST_FLAGS="-k 'FrozenRoleCapabilityCatalogTests or ordinary_generic_write_rejects or historical_rollback_cannot_restore or constrained_role_save_rejects or deployment_command_migrates or manager_assignment_is_limited_by_contract_allowlist or role_definition_administration_matrix_and_click_without_field'"
```

Result: 10 passed, 146 deselected, 13 subtests passed.

The executor additionally completed the full Settings Center module (104
passed), targeted account regressions (6 passed), Python compilation, and
`git diff --check`.

## Review notes

- The Git comparison path is repository-owned and cannot be redirected through
  the runtime environment override.
- The special migration cannot change the role set, `$administration`, role
  descriptions, explicit protection metadata, or unchanged grants.
- A reverse deployment must use a reviewed Git change and the same migration
  command; ordinary rollback remains intentionally closed to historical catalog
  metadata.
- The new management command must be included in the final generated project
  structure before block acceptance.

## Residual scope

No runtime catalog was changed by this package. Task 02 and subsequent role
administration packages remain pending, as do final profile/full verification,
workflow archival, exact-SHA Sol review, merge, and push.
